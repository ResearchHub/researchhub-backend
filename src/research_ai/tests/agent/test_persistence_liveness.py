"""Reclaiming executions whose worker stopped heartbeating."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_persistence import (
    AgentChatService,
    AgentExecutionLivenessService,
    AgentExecutionService,
)
from research_ai.services.usage_budget import (
    UsageWorkInProgressError,
    atomic_turn_admission,
)
from user.tests.helpers import create_random_authenticated_user


class AgentExecutionLivenessTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("liveness")
        self.conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        self.liveness = AgentExecutionLivenessService()
        self.lapsed = timezone.now() - timedelta(seconds=1)
        self.live = timezone.now() + timedelta(minutes=1)

    def _queued_turn(self, *, lease, conversation=None, text="Summarize the note"):
        prepared = AgentChatService().prepare_turn(
            conversation or self.conversation, text, pending=True
        )
        AgentExecution.objects.filter(id=prepared.execution.id).update(
            usage_reservation_expires_at=lease
        )
        prepared.execution.refresh_from_db()
        return prepared.execution

    def _claimed_turn(self, *, lease, conversation=None):
        execution = self._queued_turn(lease=lease, conversation=conversation)
        recorder = AgentExecutionService().claim_pending(execution)
        AgentExecution.objects.filter(id=execution.id).update(
            usage_reservation_expires_at=lease
        )
        recorder.execution.refresh_from_db()
        return recorder

    def test_a_running_turn_whose_lease_lapsed_is_failed_as_worker_lost(self):
        # Arrange
        execution = self._claimed_turn(lease=self.lapsed).execution

        # Act
        reclaimed = self.liveness.reclaim_lost()

        # Assert
        self.assertEqual([item.id for item in reclaimed], [execution.id])
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.stop_reason, "worker_lost")
        self.assertEqual(execution.error_type, "WorkerLostError")
        self.assertIsNone(execution.usage_reservation_expires_at)
        self.assertIsNotNone(execution.finished_at)

    def test_a_running_turn_with_a_live_lease_is_left_alone(self):
        # Arrange
        execution = self._claimed_turn(lease=self.live).execution

        # Act
        reclaimed = self.liveness.reclaim_lost()

        # Assert
        self.assertEqual(reclaimed, [])
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)

    def test_a_run_that_never_reserved_budget_is_not_a_candidate(self):
        # Arrange: a directly started run holds no lease, so silence says nothing.
        recorder = AgentExecutionService().start(self.conversation)

        # Act
        reclaimed = self.liveness.reclaim_lost()

        # Assert
        self.assertEqual(reclaimed, [])
        recorder.execution.refresh_from_db()
        self.assertEqual(recorder.execution.status, AgentExecution.Status.RUNNING)

    def test_a_queued_turn_past_its_claim_deadline_is_failed_and_keeps_its_prompt(
        self,
    ):
        # Arrange
        execution = self._queued_turn(lease=self.lapsed)

        # Act
        reclaimed = self.liveness.reclaim_lost()

        # Assert: sealed, its prompt preserved for the next turn's context, and
        # nothing left for a task delivered later to claim.
        self.assertEqual([item.id for item in reclaimed], [execution.id])
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.stop_reason, "worker_lost")
        self.assertEqual(
            [message.role for message in execution.context_messages.all()], ["user"]
        )
        self.assertIsNone(AgentExecutionService().claim_pending(execution))

    def test_reclaiming_can_be_scoped_to_one_user(self):
        # Arrange
        other = AgentConversation.objects.create(
            user=create_random_authenticated_user("liveness-other"),
            workflow="notebook_chat",
        )
        mine = self._claimed_turn(lease=self.lapsed).execution
        theirs = self._claimed_turn(lease=self.lapsed, conversation=other).execution

        # Act
        reclaimed = self.liveness.reclaim_lost(user=self.user)

        # Assert
        self.assertEqual([item.id for item in reclaimed], [mine.id])
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, AgentExecution.Status.RUNNING)

    def test_reclaiming_forgets_an_answer_the_user_never_received(self):
        # Arrange: the worker recorded the prompt and its closing answer, then
        # died before publishing the answer.
        recorder = self._claimed_turn(lease=self.lapsed)
        recorder.record_message(
            Message(role="user", content=[TextBlock(text="Summarize the note")])
        )
        recorder.record_message(
            Message(role="assistant", content=[TextBlock(text="Here is a summary.")])
        )

        # Act
        self.liveness.reclaim_lost()

        # Assert
        roles = [message.role for message in recorder.execution.context_messages.all()]
        self.assertEqual(roles, ["user"])

    def test_a_reclaimed_turn_frees_admission_and_the_conversation(self):
        # Arrange
        execution = self._claimed_turn(lease=self.lapsed).execution
        with (
            self.assertRaises(UsageWorkInProgressError),
            atomic_turn_admission(self.user),
        ):
            pass

        # Act
        self.liveness.reclaim_lost(user=self.user)

        # Assert
        with atomic_turn_admission(self.user):
            pass
        prepared = AgentChatService().prepare_turn(
            self.conversation, "Try again", pending=True
        )
        self.assertEqual(prepared.execution.context_parent_id, execution.id)

    def test_seal_lost_fails_an_active_execution_whatever_its_lease(self):
        # Arrange: a trace execution with no reservation of its own, whose
        # owning job's worker is known to be gone.
        recorder = AgentExecutionService().start(self.conversation)

        # Act
        sealed = self.liveness.seal_lost(recorder.execution)

        # Assert
        self.assertTrue(sealed)
        recorder.execution.refresh_from_db()
        self.assertEqual(recorder.execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(recorder.execution.stop_reason, "worker_lost")
        self.assertFalse(self.liveness.seal_lost(recorder.execution))

    def test_a_reclaimed_turn_renders_a_retryable_public_error(self):
        # Arrange
        self._claimed_turn(lease=self.lapsed)
        self.liveness.reclaim_lost()

        # Act
        (entry,) = AgentChatService().representation(self.conversation)["executions"]

        # Assert
        self.assertEqual(entry["error"]["code"], "agent_failed")
        self.assertTrue(entry["error"]["retryable"])
        self.assertNotIn("heartbeat", entry["error"]["message"])
