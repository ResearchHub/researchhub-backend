"""Cooperative cancellation of an agent execution."""

from unittest.mock import patch

from django.test import TestCase

from research_ai.models import (
    AgentConversation,
    AgentConversationMessage,
    AgentExecution,
)
from research_ai.services.agent.loop import AgentResult
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
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
from research_ai.services.usage_budget.reservation import reservation_deadline
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    agent,
    text_turn,
    tool_turn,
)


def _finished_run(*, final_text, stop_reason, iterations=1):
    """The subset of AgentResult the recorder's terminal hook reads."""
    return AgentResult(
        messages=[],
        final_text=final_text,
        stop_reason=stop_reason,
        iterations=iterations,
    )


class AgentCancellationTests(TestCase):
    def setUp(self):
        self.conversation = AgentConversation.objects.create(workflow="notebook_chat")
        self.cancels = AgentExecutionCancelService()

    def _running(self):
        return AgentExecutionService().start(
            self.conversation, provider="fake", model="fake-model-v1"
        )

    def _chat_turn(self, text="Summarize the note"):
        """A claimed turn that publishes its answer, as a real chat turn does.

        ``start`` defaults to not publishing, so anything about the divergence
        between chat and context has to come through here or it proves nothing.
        """
        prepared = AgentChatService().prepare_turn(
            self.conversation, text, pending=True
        )
        self.assertTrue(prepared.execution.publish_output_to_chat)
        return AgentExecutionService().claim_pending(prepared.execution)

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

    def test_running_cancellation_reserves_budget_until_worker_unwinds(self):
        # Arrange: this execution owns the budgeted user's single-flight slot.
        recorder = self._running()
        # Act: the request reports cancellation before the provider call returns.
        self.cancels.cancel(recorder.execution)

        # Assert: the lease tracks the in-flight call until its worker returns.
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertIsNotNone(execution.usage_reservation_expires_at)
        self.assertFalse(recorder.on_run_failed(InterruptedError("cancelled")))
        execution.refresh_from_db()
        self.assertIsNone(execution.usage_reservation_expires_at)

    def test_pending_cancellation_releases_budget_immediately(self):
        # Arrange: no worker or provider call has claimed this execution.
        execution = AgentExecutionService().create_pending(self.conversation)
        execution.usage_reservation_expires_at = reservation_deadline()
        execution.save(update_fields=["usage_reservation_expires_at"])

        # Act
        self.cancels.cancel(execution)

        # Assert
        execution.refresh_from_db()
        self.assertIsNone(execution.usage_reservation_expires_at)

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

    def test_a_cancelled_run_does_not_pay_for_another_provider_call(self):
        # Arrange: a turn that called a tool. The cancel lands *after* the tool
        # result was durably recorded, so every write this turn made saw a live
        # execution and none of them refused -- the next thing the run would do
        # is ask the model again.
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
        cancels = self.cancels
        original = DatabaseAgentRecorder.record_message

        def _cancel_after_tool_result(self_recorder, message, *, turn=None):
            original(self_recorder, message, turn=turn)
            if any(isinstance(block, ToolResultBlock) for block in message.content):
                cancels.cancel(self_recorder.execution)

        # Act
        with (
            patch.object(
                DatabaseAgentRecorder, "record_message", _cancel_after_tool_result
            ),
            self.assertRaises(InterruptedError),
        ):
            agent(provider, recorder, tools).run("Read the note")

        # Assert: the tool ran -- the cancel really did land after the turn was
        # under way -- and the second model request was never made. A provider
        # call is the costliest thing an iteration does and can hold the worker
        # for the vendor SDK's entire retry budget, so waiting for the next
        # durable write to notice would be paid for in tokens and in a worker
        # nobody is waiting on.
        self.assertEqual(dispatched, ["read"])
        self.assertEqual(len(provider.calls), 1)

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

    def test_terminal_hooks_report_whether_they_sealed_the_run(self):
        # Arrange
        recorder = self._running()

        # Act & Assert: the hook that seals the run says so; a repeat on the
        # sealed row reports no transition.
        self.assertTrue(recorder.on_run_failed(RuntimeError("boom")))
        self.assertFalse(recorder.on_run_failed(RuntimeError("boom")))
        recorder = self._running()
        result = _finished_run(final_text="done", stop_reason="end_turn")
        self.assertTrue(recorder.on_run_finished(result))
        self.assertFalse(recorder.on_run_finished(result))

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

    def test_cancelling_forgets_an_answer_the_user_never_received(self):
        # Arrange: the run recorded its closing answer, then the cancel landed
        # before ``on_run_finished`` could transition and publish it. Publication
        # requires SUCCEEDED, so that answer is never delivered -- not even by the
        # repair path.
        recorder = self._chat_turn()
        recorder.record_message(
            Message(role="user", content=[TextBlock(text="Summarize the note")])
        )
        recorder.record_message(
            Message(role="assistant", content=[TextBlock(text="Here is the summary")]),
            turn=text_turn("Here is the summary"),
        )

        # Act
        self.cancels.cancel(recorder.execution)
        recorder.on_run_finished(
            _finished_run(final_text="Here is the summary", stop_reason="end_turn")
        )

        # Assert: nothing was published, so the answer is gone from the context
        # the next turn continues from -- otherwise the model would resume as
        # though it had already replied.
        self.assertFalse(
            AgentConversationMessage.objects.filter(
                generated_by_execution=recorder.execution,
            ).exists()
        )
        contexts = AgentContextService().for_continuation(
            self.conversation, include_partial=True
        )
        self.assertEqual([message.role for message in contexts], ["user"])

    def test_cancelling_keeps_an_answer_the_user_did_receive(self):
        # Arrange: the run finished and published before anyone pressed stop, so
        # the answer is on screen and must stay in the context behind it. What
        # protects it is that a succeeded execution is terminal and cancelling
        # stops there -- the trim never runs at all. Pinned because moving the
        # trim ahead of that early return would silently retract a delivered
        # answer from the model's view of the conversation.
        recorder = self._chat_turn()
        recorder.record_message(
            Message(role="assistant", content=[TextBlock(text="Here is the summary")]),
            turn=text_turn("Here is the summary"),
        )
        recorder.on_run_finished(
            _finished_run(final_text="Here is the summary", stop_reason="end_turn")
        )

        # Act
        self.cancels.cancel(recorder.execution)

        # Assert: the cancel is a no-op on a finished turn, and the delivered
        # answer survives.
        self.assertEqual(recorder.execution.context_messages.count(), 1)

    def test_cancelling_keeps_an_assistant_turn_that_opened_tool_calls(self):
        # Arrange: an assistant turn holding tool calls is lineage, not an
        # answer. A later turn seals its open calls, so dropping it would leave
        # tool results attached to nothing.
        recorder = self._chat_turn()
        recorder.record_message(
            Message(
                role="assistant",
                content=[
                    TextBlock(text="reading the note"),
                    ToolUseBlock(id="c1", name="read_note", input={}),
                ],
            ),
            turn=tool_turn("c1", "read_note", {}),
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
