"""Liveness sweeps and cooperative cancellation."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
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
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    agent,
    text_turn,
    tool_turn,
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

    def test_one_slow_retrying_provider_call_is_not_reclaimed(self):
        # Arrange: the worst legitimate silence is a single provider call, and
        # one is not quick -- a 600s read retried inside the SDK up to 9 attempts
        # means ~90 minutes can pass between writes with nothing wrong.
        execution = self._execution(
            AgentExecution.Status.RUNNING, age=timedelta(minutes=90)
        )

        # Act
        reclaimed = AgentLivenessService().reclaim_stalled()

        # Assert: the default timeout has to clear that, or the sweep fails a
        # run that was working.
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

    def test_a_provider_call_inside_a_tool_handler_keeps_the_run_alive(self):
        # Arrange: the shape of proposal drafting's submit gate. The handler
        # judges the draft with provider calls of its own, so between the loop
        # dispatching the tool and the handler returning, the loop writes
        # nothing at all -- several provider calls' worth of silence on a run
        # that is working the whole time.
        recorder = AgentExecutionService().start(
            self.conversation, provider="fake", model="fake-model-v1"
        )
        stale = timezone.now() - (HEARTBEAT + timedelta(minutes=1))
        judge = FakeProvider([text_turn("4/5"), text_turn("5/5")])
        swept = {}

        def _submit(_args):
            # Age out everything the loop wrote before this call, so only the
            # judging below can keep the row out of the sweep's reach.
            AgentExecution.objects.filter(id=recorder.execution.id).update(
                last_activity_at=stale
            )
            for _ in range(2):
                judge.complete(
                    system_prompt="score this",
                    messages=[],
                    rendered_tools={},
                    max_tokens=64,
                    temperature=0.0,
                )
            swept["reclaimed"] = self.liveness.reclaim_stalled().total
            return {"accepted": True}

        tools = [Tool("submit", "submit", {"type": "object"}, _submit)]
        provider = FakeProvider([tool_turn("c1", "submit", {}), text_turn("done")])

        # Act
        result = agent(provider, recorder, tools).run("Draft it")

        # Assert: the janitor left it alone, so the run finished instead of
        # having its next write rejected as no longer owning the execution.
        self.assertEqual(swept["reclaimed"], 0)
        self.assertEqual(result.final_text, "done")

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

    def test_cancelling_stops_the_run_before_a_tool_takes_effect(self):
        # Arrange: a turn that asked for two tools. Cancellation lands after the
        # assistant message is recorded and before dispatch -- the window where
        # the next durable write is not until *after* the tools have run.
        recorder = self._running()
        dispatched = []

        def _tool(_args):
            dispatched.append("edit")
            return {"ok": True}

        tools = [
            Tool("edit_note", "edit", {"type": "object"}, _tool),
            Tool("read_note", "read", {"type": "object"}, _tool),
        ]
        provider = FakeProvider(
            [
                AssistantTurn(
                    text_blocks=[TextBlock(text="editing now")],
                    tool_calls=[
                        ToolUseBlock(id="c1", name="edit_note", input={}),
                        ToolUseBlock(id="c2", name="read_note", input={}),
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                text_turn("done"),
            ]
        )
        liveness = self.liveness

        original = DatabaseAgentRecorder.record_message

        def _cancel_after_assistant_turn(self_recorder, message, *, turn=None):
            original(self_recorder, message, turn=turn)
            if turn is not None:
                liveness.cancel(self_recorder.execution)

        # Act
        with (
            patch.object(
                DatabaseAgentRecorder, "record_message", _cancel_after_assistant_turn
            ),
            self.assertRaises(InterruptedError),
        ):
            agent(provider, recorder, tools).run("Edit the note")

        # Assert: the note was never touched. Cancellation frees the
        # conversation at once, so a tool running past it could write the same
        # document as the replacement turn.
        self.assertEqual(dispatched, [])
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)

    def test_a_recorder_that_cannot_answer_does_not_halt_a_healthy_run(self):
        # Arrange: is_active is advisory -- a failing check must not be able to
        # stop a run that is fine.
        recorder = self._running()
        dispatched = []
        tools = [
            Tool(
                "read_note",
                "read",
                {"type": "object"},
                lambda _a: dispatched.append("read") or {"ok": True},
            )
        ]
        provider = FakeProvider([tool_turn("c1", "read_note", {}), text_turn("done")])

        # Act
        with patch.object(
            DatabaseAgentRecorder,
            "is_active",
            side_effect=RuntimeError("database hiccup"),
        ):
            result = agent(provider, recorder, tools).run("Read the note")

        # Assert
        self.assertEqual(dispatched, ["read"])
        self.assertEqual(result.final_text, "done")

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
