"""Liveness-sweep coverage: stale executions are sealed, live ones are not."""

from datetime import timedelta

from django.utils import timezone

from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_persistence import (
    AgentChatService,
    AgentExecutionReaperService,
    AgentExecutionService,
)
from research_ai.services.agent_persistence.reaper_service import (
    STALLED_ERROR_TYPE,
    STALLED_STOP_REASON,
)
from research_ai.tests.agent.persistence_test_helpers import AgentPersistenceTestCase


class AgentExecutionReaperTests(AgentPersistenceTestCase):
    def setUp(self):
        super().setUp()
        self.chat = AgentChatService()
        self.reaper = AgentExecutionReaperService()

    def _pending_turn(self, text="Please summarize."):
        return self.chat.prepare_turn(self.conversation, text, pending=True).execution

    def _running_turn(self, text="Please summarize."):
        execution = self._pending_turn(text)
        recorder = AgentExecutionService().claim_pending(execution)
        self.assertIsNotNone(recorder)
        return execution, recorder

    @staticmethod
    def _age(execution, minutes, **field_overrides):
        past = timezone.now() - timedelta(minutes=minutes)
        fields = {"last_activity_at": past, "created_date": past}
        fields.update(field_overrides)
        AgentExecution.objects.filter(id=execution.id).update(**fields)
        execution.refresh_from_db()

    def test_stale_running_execution_is_interrupted_with_error_fields(self):
        # Arrange
        execution, _recorder = self._running_turn()
        self._age(execution, minutes=20)

        # Act
        reaped = self.reaper.reap()

        # Assert
        execution.refresh_from_db()
        self.assertEqual([reaped_row.id for reaped_row in reaped], [execution.id])
        self.assertEqual(execution.status, AgentExecution.Status.INTERRUPTED)
        self.assertEqual(execution.stop_reason, STALLED_STOP_REASON)
        self.assertEqual(execution.error_type, STALLED_ERROR_TYPE)
        self.assertIn("worker likely died", execution.error_message)
        self.assertIsNotNone(execution.finished_at)

    def test_fresh_running_execution_is_left_alone(self):
        # Arrange: heartbeat stamped at claim time, moments ago.
        execution, _recorder = self._running_turn()

        # Act
        reaped = self.reaper.reap()

        # Assert
        execution.refresh_from_db()
        self.assertEqual(reaped, [])
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)

    def test_stale_pending_execution_is_interrupted_and_context_seeded(self):
        # Arrange: a queued turn whose task was lost before any worker claimed
        # it. Its prompt exists only as the chat message that triggered it.
        execution = self._pending_turn("The lost question")
        self._age(execution, minutes=20)

        # Act
        reaped = self.reaper.reap()

        # Assert: sealed, and the prompt was seeded into the durable context
        # so the next turn's model view still contains it.
        execution.refresh_from_db()
        self.assertEqual([reaped_row.id for reaped_row in reaped], [execution.id])
        self.assertEqual(execution.status, AgentExecution.Status.INTERRUPTED)
        self.assertIn("not claimed", execution.error_message)
        (context_row,) = execution.context_messages.all()
        self.assertEqual(context_row.content[0]["text"], "The lost question")

    def test_fresh_pending_execution_is_left_alone(self):
        # Arrange
        execution = self._pending_turn()

        # Act
        reaped = self.reaper.reap()

        # Assert
        execution.refresh_from_db()
        self.assertEqual(reaped, [])
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)

    def test_running_execution_without_heartbeat_falls_back_to_updated_date(self):
        # Arrange: a defensive path -- claim always stamps the heartbeat, so
        # only a manually blanked row can look like this.
        execution, _recorder = self._running_turn()
        past = timezone.now() - timedelta(minutes=20)
        AgentExecution.objects.filter(id=execution.id).update(
            last_activity_at=None, updated_date=past
        )

        # Act
        reaped = self.reaper.reap()

        # Assert
        execution.refresh_from_db()
        self.assertEqual(len(reaped), 1)
        self.assertEqual(execution.status, AgentExecution.Status.INTERRUPTED)

    def test_zombie_turns_unpublished_closing_answer_is_dropped(self):
        # Arrange: the worker died after durably recording its final answer
        # but before sealing SUCCEEDED -- the answer was never published, so
        # the next turn must not resume from a reply the user never saw.
        execution, recorder = self._running_turn("Question")
        recorder.record_message(Message(role="user", content=[TextBlock(text="Q")]))
        recorder.record_message(
            Message(role="assistant", content=[TextBlock(text="Unseen answer")])
        )
        self._age(execution, minutes=20)

        # Act
        self.reaper.reap()

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.INTERRUPTED)
        roles = list(
            execution.context_messages.order_by("sequence").values_list(
                "role", flat=True
            )
        )
        self.assertEqual(roles, ["user"])

    def test_reaped_conversation_accepts_the_next_turn(self):
        # Arrange: the exact failure being fixed -- a dead worker's RUNNING
        # row used to 409-block the conversation forever.
        execution, _recorder = self._running_turn()
        self._age(execution, minutes=20)

        # Act
        self.reaper.reap()
        next_turn = self.chat.prepare_turn(
            self.conversation, "Trying again", pending=True
        )

        # Assert
        self.assertEqual(next_turn.execution.status, AgentExecution.Status.PENDING)

    def test_terminal_executions_are_never_reaped(self):
        # Arrange
        execution, recorder = self._running_turn()
        recorder.on_run_failed(RuntimeError("already sealed"))
        self._age(execution, minutes=60)

        # Act
        reaped = self.reaper.reap()

        # Assert
        execution.refresh_from_db()
        self.assertEqual(reaped, [])
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)

    def test_sweep_covers_every_workflow_sharing_the_models(self):
        # Arrange: a headless proposal-draft run abandoned by its worker.
        conversation = AgentConversation.objects.create(workflow="proposal_draft")
        recorder = AgentExecutionService().start(conversation, provider="fake")
        execution = recorder.execution
        self._age(execution, minutes=20)

        # Act
        reaped = self.reaper.reap()

        # Assert
        execution.refresh_from_db()
        self.assertEqual([reaped_row.id for reaped_row in reaped], [execution.id])
        self.assertEqual(execution.status, AgentExecution.Status.INTERRUPTED)

    def test_candidate_whose_heartbeat_advanced_is_skipped_under_the_lock(self):
        # Arrange: the row looked stale when the sweep scanned, but its worker
        # wrote a heartbeat before the sweep reached it.
        execution, _recorder = self._running_turn()

        # Act: the per-row seal re-checks staleness and must refuse.
        sealed = self.reaper._reap_one(execution.id, timezone.now())

        # Assert
        execution.refresh_from_db()
        self.assertIsNone(sealed)
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)

    def test_reaped_turn_renders_an_interrupted_public_error(self):
        # Arrange
        execution, _recorder = self._running_turn()
        self._age(execution, minutes=20)

        # Act
        self.reaper.reap()
        (entry,) = self.chat.representation(self.conversation)["executions"]

        # Assert: the public payload names the interruption without leaking
        # the internal message.
        self.assertEqual(entry["error"]["code"], "agent_interrupted")
        self.assertNotIn("worker", entry["error"]["message"])
