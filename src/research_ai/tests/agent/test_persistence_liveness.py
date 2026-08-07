"""Liveness sweeps and cooperative cancellation."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_persistence import (
    AgentChatService,
    AgentConversationBusyError,
    AgentExecutionService,
    AgentLivenessService,
    DatabaseAgentRecorder,
)
from research_ai.services.agent_persistence.liveness_service import (
    NEVER_STARTED_ERROR_TYPE,
    STALLED_ERROR_TYPE,
)

HEARTBEAT = timedelta(minutes=15)
QUEUE = timedelta(minutes=30)


class AgentLivenessSweepTests(TestCase):
    def setUp(self):
        self.conversation = AgentConversation.objects.create(workflow="notebook_chat")
        self.liveness = AgentLivenessService(
            heartbeat_timeout=HEARTBEAT, queue_timeout=QUEUE
        )

    def _execution(self, status, *, age=timedelta(0), attempt=1):
        """An execution whose heartbeat (or queue wait) is ``age`` old."""
        moment = timezone.now() - age
        execution = AgentExecution.objects.create(
            conversation=self.conversation,
            attempt=attempt,
            status=status,
            started_at=(moment if status != AgentExecution.Status.PENDING else None),
            last_activity_at=(
                moment if status != AgentExecution.Status.PENDING else None
            ),
        )
        # created_date is auto-set, so a stale queue wait has to be written back.
        AgentExecution.objects.filter(id=execution.id).update(created_date=moment)
        execution.refresh_from_db()
        return execution

    def test_running_execution_past_the_heartbeat_is_reclaimed(self):
        # Arrange: a worker that died without landing a terminal status.
        execution = self._execution(
            AgentExecution.Status.RUNNING, age=HEARTBEAT + timedelta(minutes=1)
        )

        # Act
        reclaimed = self.liveness.reclaim_stalled()

        # Assert
        self.assertEqual(reclaimed.stalled, 1)
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.INTERRUPTED)
        self.assertEqual(execution.error_type, STALLED_ERROR_TYPE)
        self.assertEqual(execution.stop_reason, "stalled")
        self.assertIsNotNone(execution.finished_at)
        self.assertIsNotNone(execution.duration_ms)

    def test_a_recent_heartbeat_is_left_alone(self):
        # Arrange: slow, but alive -- it wrote something a minute ago.
        execution = self._execution(
            AgentExecution.Status.RUNNING, age=timedelta(minutes=1)
        )

        # Act
        reclaimed = self.liveness.reclaim_stalled()

        # Assert
        self.assertEqual(reclaimed.total, 0)
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)

    def test_pending_execution_no_worker_ever_claimed_is_reclaimed(self):
        # Arrange: the broker accepted the task and never delivered it.
        execution = self._execution(
            AgentExecution.Status.PENDING, age=QUEUE + timedelta(minutes=1)
        )

        # Act
        reclaimed = self.liveness.reclaim_stalled()

        # Assert
        self.assertEqual(reclaimed.never_started, 1)
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.INTERRUPTED)
        self.assertEqual(execution.error_type, NEVER_STARTED_ERROR_TYPE)

    def test_a_recently_queued_execution_is_left_alone(self):
        # Arrange: queued a moment ago; a worker may still be picking it up.
        execution = self._execution(
            AgentExecution.Status.PENDING, age=timedelta(minutes=1)
        )

        # Act
        self.liveness.reclaim_stalled()

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)

    def test_terminal_executions_are_never_touched(self):
        # Arrange: old, but finished -- nothing to reclaim.
        execution = self._execution(AgentExecution.Status.SUCCEEDED, age=HEARTBEAT * 10)

        # Act
        reclaimed = self.liveness.reclaim_stalled()

        # Assert
        self.assertEqual(reclaimed.total, 0)
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)

    def test_a_long_setup_phase_writing_no_rows_is_not_reclaimed(self):
        # Arrange: the proposal-draft shape. Its execution is created before the
        # RFP fetch and the profile build -- itself an agent run of up to 16 tool
        # turns that writes nothing against this execution -- so a healthy run
        # can sit a long while on its creation-time heartbeat.
        execution = self._execution(
            AgentExecution.Status.RUNNING, age=timedelta(minutes=40)
        )

        # Act
        reclaimed = AgentLivenessService().reclaim_stalled()

        # Assert: the default timeout has to clear that gap, or the sweep fails
        # a run that was working.
        self.assertEqual(reclaimed.total, 0)
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)

    def test_a_heartbeat_protects_a_run_the_sweep_would_have_reclaimed(self):
        # Arrange: past the timeout, so the next sweep would take it.
        execution = self._execution(
            AgentExecution.Status.RUNNING, age=HEARTBEAT + timedelta(minutes=1)
        )
        recorder = DatabaseAgentRecorder(execution)

        # Act
        self.assertTrue(recorder.heartbeat())
        reclaimed = self.liveness.reclaim_stalled()

        # Assert
        self.assertEqual(reclaimed.total, 0)
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)

    def test_a_heartbeat_on_a_terminal_run_reports_false_and_writes_nothing(self):
        # Arrange: cancelled from another process while a caller still holds a
        # recorder for it.
        recorder = AgentExecutionService().start(
            self.conversation, provider="fake", model="fake-model-v1"
        )
        AgentLivenessService().cancel(recorder.execution)
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        cancelled_at = execution.last_activity_at

        # Act
        alive = recorder.heartbeat()

        # Assert: no heartbeat can revive a run, and the timestamps its
        # cancellation left behind are not moved.
        self.assertFalse(alive)
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(execution.last_activity_at, cancelled_at)

    def test_reclaiming_unblocks_a_conversation_a_dead_worker_stranded(self):
        # Arrange: one active execution per conversation is enforced, so the
        # abandoned row refuses every later turn.
        self._execution(
            AgentExecution.Status.RUNNING, age=HEARTBEAT + timedelta(minutes=1)
        )
        chat = AgentChatService()
        with self.assertRaises(AgentConversationBusyError):
            chat.prepare_turn(self.conversation, "Are you there?", pending=True)

        # Act
        self.liveness.reclaim_stalled()

        # Assert: the user can simply ask again.
        prepared = chat.prepare_turn(self.conversation, "Are you there?", pending=True)
        self.assertEqual(prepared.execution.status, AgentExecution.Status.PENDING)


class AgentCancellationTests(TestCase):
    def setUp(self):
        self.conversation = AgentConversation.objects.create(workflow="notebook_chat")
        self.liveness = AgentLivenessService()

    def _running(self):
        return AgentExecutionService().start(
            self.conversation, provider="fake", model="fake-model-v1"
        )

    def test_cancelling_a_running_execution_records_no_failure(self):
        # Arrange
        recorder = self._running()

        # Act
        cancelled = self.liveness.cancel(recorder.execution)

        # Assert: a cancellation is the user's decision, not an error, so the
        # status carries it and the error fields stay empty.
        self.assertTrue(cancelled)
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(execution.stop_reason, "cancelled")
        self.assertEqual(execution.error_type, "")
        self.assertIsNotNone(execution.finished_at)

    def test_cancelling_stops_the_worker_at_its_next_durable_write(self):
        # Arrange: a run in flight, cancelled from another process.
        recorder = self._running()
        self.liveness.cancel(recorder.execution)

        # Act & Assert: the recorder refuses to extend a terminal execution, so
        # the loop unwinds instead of appending to context nobody will replay.
        with self.assertRaises(InterruptedError):
            recorder.record_message(
                Message(role="assistant", content=[TextBlock(text="still going")])
            )

    def test_cancelling_an_already_terminal_execution_reports_false(self):
        # Arrange
        recorder = self._running()
        self.liveness.cancel(recorder.execution)

        # Act
        again = self.liveness.cancel(recorder.execution)

        # Assert: the ordinary race of stopping a turn that already stopped.
        self.assertFalse(again)

    def test_cancelling_frees_the_conversation_for_the_next_turn(self):
        # Arrange
        recorder = self._running()

        # Act
        self.liveness.cancel(recorder.execution)

        # Assert
        prepared = AgentChatService().prepare_turn(
            self.conversation, "Never mind, try this instead.", pending=True
        )
        self.assertEqual(prepared.execution.status, AgentExecution.Status.PENDING)
