"""Cooperative cancellation of an agent execution."""

from unittest.mock import patch

from django.test import TestCase

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
    AgentContextService,
    AgentExecutionCancelService,
    AgentExecutionService,
    DatabaseAgentRecorder,
)
from research_ai.services.agent_persistence.content import serialize_trace_message
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    agent,
    text_turn,
    tool_turn,
)


class AgentCancellationTests(TestCase):
    def setUp(self):
        self.conversation = AgentConversation.objects.create(workflow="notebook_chat")
        self.cancels = AgentExecutionCancelService()

    def _running(self):
        return AgentExecutionService().start(
            self.conversation, provider="fake", model="fake-model-v1"
        )

    def test_cancelling_a_running_execution_records_no_failure(self):
        # Arrange
        recorder = self._running()

        # Act
        cancelled = self.cancels.cancel(recorder.execution)

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
        self.cancels.cancel(recorder.execution)

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
        cancels = self.cancels

        original = DatabaseAgentRecorder.record_message

        def _cancel_after_assistant_turn(self_recorder, message, *, turn=None):
            original(self_recorder, message, turn=turn)
            if turn is not None:
                cancels.cancel(self_recorder.execution)

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
        self.cancels.cancel(recorder.execution)

        # Act
        again = self.cancels.cancel(recorder.execution)

        # Assert: the ordinary race of stopping a turn that already stopped.
        self.assertFalse(again)

    def test_a_trace_write_already_in_flight_cannot_reopen_the_outcome(self):
        # Arrange: recording a message writes durable context first, then the
        # optional trace. Cancellation commits in the gap between the two, so
        # the context write saw a live execution and the trace write finds a
        # terminal one -- and it is holding the turn's own stop reason.
        recorder = self._running()
        traced_before = recorder.execution.messages.count()

        def _cancel_then_serialize(message):
            self.cancels.cancel(recorder.execution)
            return serialize_trace_message(message)

        # Act: patched where the recorder reads it, since it binds the symbol at
        # import time.
        with patch(
            "research_ai.services.agent_persistence.recorder.serialize_trace_message",
            _cancel_then_serialize,
        ):
            recorder.record_message(
                Message(role="assistant", content=[TextBlock(text="mid-flight")]),
                turn=text_turn("mid-flight"),
            )

        # Assert: the trace row still lands -- the turn really happened -- but
        # the cancellation stands. Overwriting stop_reason here would report a
        # CANCELLED execution as having stopped for `end_turn`, and moving
        # last_activity_at would push it past finished_at.
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(execution.stop_reason, "cancelled")
        self.assertGreater(execution.messages.count(), traced_before)
        self.assertIsNotNone(execution.finished_at)
        self.assertLessEqual(execution.last_activity_at, execution.finished_at)

    def test_cancelling_a_queued_turn_keeps_its_prompt_in_the_model_context(self):
        # Arrange: a turn cancelled while still PENDING never ran, so the worker
        # never recorded its seed prompt as context. That prompt is on screen in
        # the chat, and a cancelled execution is a continuation parent whose
        # context the next turn inherits -- so without it the model would answer
        # a conversation missing a message the user can see.
        prepared = AgentChatService().prepare_turn(
            self.conversation, "Summarize the note", pending=True
        )
        self.assertEqual(prepared.execution.context_messages.count(), 0)

        # Act
        self.cancels.cancel(prepared.execution)

        # Assert
        contexts = AgentContextService().for_continuation(
            self.conversation, include_partial=True
        )
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].role, "user")
        self.assertIn("Summarize the note", str(contexts[0].content))

    def test_cancelling_a_running_turn_does_not_duplicate_its_prompt(self):
        # Arrange: a turn that did run recorded its own seed prompt, so the
        # rescue above must not add a second copy of it.
        prepared = AgentChatService().prepare_turn(
            self.conversation, "Summarize the note", pending=True
        )
        recorder = AgentExecutionService().claim_pending(prepared.execution)
        recorder.record_message(
            Message(role="user", content=[TextBlock(text="Summarize the note")])
        )

        # Act
        self.cancels.cancel(recorder.execution)

        # Assert
        self.assertEqual(recorder.execution.context_messages.count(), 1)

    def test_cancelling_frees_the_conversation_for_the_next_turn(self):
        # Arrange: one active execution per conversation is enforced, so an
        # execution that never reaches a terminal status refuses every later
        # turn on that conversation. Cancelling is what unsticks it -- including
        # when the worker that owned it died without landing an outcome.
        recorder = self._running()

        # Act
        self.cancels.cancel(recorder.execution)

        # Assert
        prepared = AgentChatService().prepare_turn(
            self.conversation, "Never mind, try this instead.", pending=True
        )
        self.assertEqual(prepared.execution.status, AgentExecution.Status.PENDING)
