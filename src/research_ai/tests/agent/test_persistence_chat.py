"""User-facing chat preparation, retry, publication, and repair coverage."""

import json
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext

from research_ai.models import (
    AgentConversation,
    AgentExecution,
    AgentExecutionMessage,
)
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
    AgentConversationBusyError,
    AgentConversationService,
    AgentExecutionService,
    AgentStaleRetryError,
    DatabaseAgentRecorder,
)
from research_ai.services.agent_persistence.content import (
    MAX_TRACE_MESSAGE_BYTES,
    json_size_bytes,
)
from research_ai.tests.agent.persistence_test_helpers import (
    AgentPersistenceTestCase,
    FakeProvider,
    agent,
    text_turn,
    tool_turn,
)


class ChatMessageSnapshot:
    """Serve chat rows as they stood before a concurrent publication."""

    def __init__(self, rows):
        self.rows = rows

    def filter(self, **kwargs):
        return ChatMessageSnapshot(
            [row for row in self.rows if row.is_active == kwargs["is_active"]]
        )

    def order_by(self, *_fields):
        return self.rows


class AgentChatPersistenceTests(AgentPersistenceTestCase):
    def test_backend_prompt_preserves_human_text_and_chat_filters_trace(self):
        # Arrange
        chat = AgentChatService()
        prepared = chat.prepare_turn(
            self.conversation,
            "What I actually typed",
            provider="fake",
            model="fake-model-v1",
            prompt_is_backend_composed=True,
        )
        wrapped_prompt = "Notebook context:\n...\nUser: What I actually typed"
        tool = Tool("lookup", "lookup", {"type": "object"}, lambda _args: {"secret": 1})
        provider = FakeProvider(
            [tool_turn("c1", "lookup", {}), text_turn("Visible answer")]
        )

        # Act
        agent(provider, prepared.recorder, [tool]).run(wrapped_prompt)
        representation = chat.representation(self.conversation)

        # Assert
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["What I actually typed", "Visible answer"],
        )
        first_trace = prepared.execution.messages.order_by("execution_sequence").first()
        self.assertEqual(
            first_trace.provenance, AgentExecutionMessage.Provenance.BACKEND
        )
        self.assertEqual(first_trace.content[0]["text"], wrapped_prompt)
        self.assertNotIn("secret", json.dumps(representation["messages"]))

    def test_retry_reuses_human_message_and_provenance(self):
        # Arrange
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "One human turn")
        prepared.recorder.on_run_failed(RuntimeError("temporary failure"))

        # Act
        retry = chat.prepare_retry(prepared.execution)
        agent(FakeProvider([text_turn("Recovered")]), retry.recorder).run(
            "One human turn"
        )

        # Assert
        self.assertEqual(self.conversation.chat_messages.filter(role="USER").count(), 1)
        self.assertEqual(retry.execution.trigger_message_id, prepared.human_message.id)
        self.assertEqual(retry.execution.retry_of_id, prepared.execution.id)
        self.assertEqual(
            chat.representation(self.conversation)["messages"][-1]["content"],
            "Recovered",
        )
        self.assertEqual(
            retry.execution.messages.order_by("execution_sequence").first().provenance,
            AgentExecutionMessage.Provenance.HUMAN,
        )

    def test_failed_assistant_publication_is_repaired_from_durable_intent(self):
        # Arrange
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "Question")

        # Act
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(FakeProvider([text_turn("Durable answer")]), prepared.recorder).run(
                "Question"
            )
        execution = AgentExecution.objects.get(id=prepared.execution.id)
        representation = chat.representation(self.conversation)

        # Assert
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertTrue(execution.publish_output_to_chat)
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["Question", "Durable answer"],
        )
        self.assertFalse(representation["executions"][0]["assistant_message_pending"])

    def test_large_assistant_output_repairs_as_the_same_bounded_text(self):
        # Arrange
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "Question")
        huge_answer = "x" * (MAX_TRACE_MESSAGE_BYTES * 2)

        # Act
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(FakeProvider([text_turn(huge_answer)]), prepared.recorder).run(
                "Question"
            )
        execution = AgentExecution.objects.get(id=prepared.execution.id)
        representation = chat.representation(self.conversation)

        # Assert
        stored_text = execution.final_output["text"]
        self.assertIsInstance(stored_text, str)
        self.assertTrue(execution.final_output["_truncated"])
        self.assertLessEqual(
            json_size_bytes(execution.final_output), MAX_TRACE_MESSAGE_BYTES
        )
        self.assertEqual(representation["messages"][-1]["content"], stored_text)

    def test_public_representation_does_not_expose_internal_error_message(self):
        # Arrange
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "Question")
        prepared.recorder.on_run_failed(
            RuntimeError("provider secret token must not be public")
        )

        # Act
        representation = chat.representation(self.conversation)

        # Assert: default=str because the representation carries the progress
        # timestamps as datetimes, which DRF renders on the way out.
        self.assertNotIn("secret token", json.dumps(representation, default=str))
        self.assertEqual(
            representation["executions"][0]["error"],
            {
                "code": "agent_failed",
                "message": "The agent could not complete this request.",
            },
        )

    def test_representation_reports_progress_for_a_finished_turn(self):
        # Arrange
        chat = AgentChatService()
        prepared = chat.prepare_turn(
            self.conversation,
            "Question",
            configuration={"max_iterations": 12},
        )

        # Act
        agent(FakeProvider([text_turn("Answer")]), prepared.recorder).run("Question")
        (entry,) = chat.representation(self.conversation)["executions"]

        # Assert: enough for a client to render elapsed time and "step N of M".
        self.assertIsNotNone(entry["started_at"])
        self.assertIsNotNone(entry["finished_at"])
        self.assertIsNotNone(entry["last_activity_at"])
        self.assertEqual(entry["iterations"], 1)
        self.assertEqual(entry["max_iterations"], 12)

    def test_max_iterations_is_absent_when_the_attempt_recorded_none(self):
        # Arrange: max_iterations is read from the attempt's own configuration
        # snapshot, so a run that never recorded one reports nothing rather
        # than borrowing today's settings.
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "Question")

        # Act
        agent(FakeProvider([text_turn("Answer")]), prepared.recorder).run("Question")
        (entry,) = chat.representation(self.conversation)["executions"]

        # Assert
        self.assertIsNone(entry["max_iterations"])

    def test_a_running_turn_reports_a_heartbeat_and_no_finish(self):
        # Arrange: a turn in flight, no terminal hook called.
        chat = AgentChatService()
        chat.prepare_turn(self.conversation, "Question")

        # Act
        (entry,) = chat.representation(self.conversation)["executions"]

        # Assert: last_activity_at is what lets a client tell a turn working
        # slowly from one that has gone quiet.
        self.assertEqual(entry["status"], AgentExecution.Status.RUNNING)
        self.assertIsNotNone(entry["started_at"])
        self.assertIsNotNone(entry["last_activity_at"])
        self.assertIsNone(entry["finished_at"])

    def test_public_representation_costs_the_same_however_long_the_chat_is(self):
        # Arrange
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "First")
        agent(FakeProvider([text_turn("First answer")]), first.recorder).run("First")
        second = chat.prepare_turn(self.conversation, "Second")
        agent(FakeProvider([text_turn("Second answer")]), second.recorder).run("Second")
        with CaptureQueriesContext(connection) as two_turns:
            representation = chat.representation(self.conversation)
        self.assertEqual(len(representation["executions"]), 2)

        # Act: a third turn adds an execution, a message, and a link between them
        third = chat.prepare_turn(self.conversation, "Third")
        agent(FakeProvider([text_turn("Third answer")]), third.recorder).run("Third")
        with CaptureQueriesContext(connection) as three_turns:
            representation = chat.representation(self.conversation)

        # Assert: the comparison is what rules out an N+1, not the count itself.
        # A ceiling still guards the absolute cost, loosely enough that adding
        # one query to the read is a decision rather than a broken build.
        self.assertEqual(len(representation["executions"]), 3)
        self.assertEqual(len(three_turns), len(two_turns))
        self.assertLessEqual(len(two_turns), 5)

    def test_regeneration_repair_replaces_prior_output_without_new_user_message(self):
        # Arrange
        chat = AgentChatService()
        original = chat.prepare_turn(self.conversation, "Question")
        agent(FakeProvider([text_turn("First answer")]), original.recorder).run(
            "Question"
        )
        regeneration = chat.prepare_retry(original.execution, regenerate=True)

        # Act
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(
                FakeProvider([text_turn("Better answer")]),
                regeneration.recorder,
            ).run("Question")
        representation = chat.representation(self.conversation)

        # Assert
        regeneration.execution.refresh_from_db()
        self.assertEqual(
            regeneration.execution.replaces_output_of_id,
            original.execution.id,
        )
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["Question", "Better answer"],
        )
        self.assertEqual(self.conversation.chat_messages.filter(role="USER").count(), 1)

    def test_prepare_turn_rolls_back_human_message_when_execution_start_fails(self):
        # Arrange
        chat = AgentChatService()

        # Act / Assert
        with (
            patch.object(
                AgentExecutionService,
                "start",
                side_effect=RuntimeError("execution insert failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "execution insert failed"),
        ):
            chat.prepare_turn(self.conversation, "Do not orphan me")
        self.assertFalse(self.conversation.chat_messages.exists())

    def test_prepare_turn_aborts_when_the_durable_lineage_is_unreadable(self):
        # Arrange
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "First")
        agent(FakeProvider([text_turn("Answer")]), first.recorder).run("First")
        message_count = self.conversation.chat_messages.count()
        execution_count = self.conversation.executions.count()

        # Act / Assert: every path that reads the lineage has to fail loudly.
        # Tolerating a broken one would start the model on an empty history and
        # drop the conversation so far without anyone noticing.
        with (
            patch.object(
                chat.contexts,
                "reconstruct",
                side_effect=ValueError("invalid durable context"),
            ),
            self.assertRaisesRegex(ValueError, "invalid durable context"),
        ):
            chat.prepare_turn(self.conversation, "Second")
        self.assertEqual(self.conversation.chat_messages.count(), message_count)
        self.assertEqual(self.conversation.executions.count(), execution_count)

    def test_active_turn_blocks_a_second_linear_turn_without_new_message(self):
        # Arrange
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "First")

        # Act / Assert
        with self.assertRaises(AgentConversationBusyError):
            chat.prepare_turn(self.conversation, "Second")
        self.assertEqual(self.conversation.chat_messages.count(), 1)
        self.assertEqual(self.conversation.executions.count(), 1)
        first.recorder.on_run_failed(InterruptedError("test cleanup"))

    def test_pending_execution_is_visible_and_atomically_claimed(self):
        # Arrange
        human = AgentConversationService().add_human_message(
            self.conversation, "Queued question"
        )
        service = AgentExecutionService()
        pending = service.create_pending(
            self.conversation,
            trigger_message=human,
            model="queued-model",
        )

        # Act
        before = AgentChatService().representation(self.conversation)
        recorder = service.claim_pending(pending, publish_assistant_message=True)
        second_claim = service.claim_pending(pending)

        # Assert
        self.assertEqual(
            before["executions"][0]["status"], AgentExecution.Status.PENDING
        )
        self.assertIsNotNone(recorder)
        self.assertIsNone(second_claim)
        self.assertEqual(
            AgentExecution.objects.get(id=pending.id).status,
            AgentExecution.Status.RUNNING,
        )

    def test_new_turn_keeps_the_prompt_of_a_run_that_failed(self):
        # Arrange: the second turn fails after recording its own prompt
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "First question")
        agent(FakeProvider([text_turn("First answer")]), first.recorder).run(
            "First question"
        )
        second = chat.prepare_turn(self.conversation, "Second question")
        with self.assertRaises(RuntimeError):
            agent(FakeProvider([RuntimeError("provider down")]), second.recorder).run(
                "Second question"
            )

        # Act
        third = chat.prepare_turn(self.conversation, "Third question")

        # Assert
        self.assertEqual(third.execution.context_parent_id, second.execution.id)
        self.assertEqual(
            [
                block.text
                for message in third.context
                for block in message.content
                if isinstance(block, TextBlock)
            ],
            ["First question", "First answer", "Second question"],
        )

    def test_continuing_a_stopped_run_answers_its_open_tool_calls(self):
        # Arrange: a run stops after recording tool calls but before their results
        chat = AgentChatService()
        stopped = chat.prepare_turn(self.conversation, "Interrupted question")
        stopped.recorder.record_message(
            Message(role="user", content=[TextBlock(text="Interrupted question")])
        )
        stopped.recorder.record_message(
            Message(
                role="assistant",
                content=[ToolUseBlock(id="call-1", name="lookup", input={})],
            )
        )
        stopped.recorder.on_run_failed(InterruptedError("worker stopped"))

        # Act
        resumed = chat.prepare_turn(self.conversation, "Next question")

        # Assert
        answered = [
            block.tool_use_id
            for message in resumed.context
            for block in message.content
            if isinstance(block, ToolResultBlock)
        ]
        self.assertEqual(answered, ["call-1"])
        self.assertEqual(resumed.context[-1].role, "user")

    def test_retry_ignores_later_trace_rows_when_the_prompt_row_is_lost(self):
        # Arrange: trace rows are best-effort, so drop only the prompt row
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "Question")
        agent(FakeProvider([text_turn("Answer")]), prepared.recorder).run("Question")
        prepared.execution.messages.filter(execution_sequence=1).delete()
        self.assertEqual(
            prepared.execution.messages.first().provenance,
            AgentExecutionMessage.Provenance.MODEL,
        )

        # Act
        retry = chat.prepare_retry(prepared.execution)
        agent(FakeProvider([text_turn("Recovered")]), retry.recorder).run("Question")

        # Assert
        self.assertEqual(
            retry.execution.messages.order_by("execution_sequence").first().provenance,
            AgentExecutionMessage.Provenance.HUMAN,
        )

    def test_regenerating_a_regeneration_hides_the_original_answer(self):
        # Arrange: the first answer publishes, its regeneration does not
        chat = AgentChatService()
        original = chat.prepare_turn(self.conversation, "Question")
        agent(FakeProvider([text_turn("Stale answer")]), original.recorder).run(
            "Question"
        )
        first_regeneration = chat.prepare_retry(original.execution, regenerate=True)
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(
                FakeProvider([text_turn("Lost answer")]), first_regeneration.recorder
            ).run("Question")

        # Act: the user regenerates again, and that attempt publishes
        second_regeneration = chat.prepare_retry(
            first_regeneration.execution, regenerate=True
        )
        agent(
            FakeProvider([text_turn("Better answer")]), second_regeneration.recorder
        ).run("Question")
        representation = chat.representation(self.conversation)

        # Assert
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["Question", "Better answer"],
        )

    def test_repair_skips_an_answer_a_regeneration_chain_replaced(self):
        # Arrange: neither the original nor its regeneration manages to publish
        chat = AgentChatService()
        original = chat.prepare_turn(self.conversation, "Question")
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(FakeProvider([text_turn("Stale answer")]), original.recorder).run(
                "Question"
            )
            first_regeneration = chat.prepare_retry(original.execution, regenerate=True)
            agent(
                FakeProvider([text_turn("Lost answer")]), first_regeneration.recorder
            ).run("Question")

        # Act
        second_regeneration = chat.prepare_retry(
            first_regeneration.execution, regenerate=True
        )
        agent(
            FakeProvider([text_turn("Better answer")]), second_regeneration.recorder
        ).run("Question")
        representation = chat.representation(self.conversation)

        # Assert: repair must not append the original behind its replacement
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["Question", "Better answer"],
        )
        self.assertEqual(
            [
                item["assistant_message_pending"]
                for item in representation["executions"]
                if item["id"] != second_regeneration.execution.id
            ],
            [False, False],
        )

    def test_success_through_a_terminal_tool_is_never_pending(self):
        # Arrange: a terminal tool answers, so the run records no final text
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "Question")
        submit = Tool(
            "submit",
            "submit",
            {"type": "object"},
            lambda _args: {"saved": True},
            is_terminal=True,
        )
        provider = FakeProvider(
            [
                AssistantTurn(
                    text_blocks=[],
                    tool_calls=[ToolUseBlock(id="c1", name="submit", input={})],
                    stop_reason=StopReason.TOOL_USE,
                )
            ]
        )

        # Act
        result = agent(provider, prepared.recorder, [submit]).run("Question")
        with patch.object(DatabaseAgentRecorder, "publish_assistant_output") as publish:
            representation = chat.representation(self.conversation)

        # Assert
        self.assertEqual(result.final_text, "")
        publish.assert_not_called()
        self.assertFalse(representation["executions"][0]["assistant_message_pending"])
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["Question"],
        )

    def test_next_turn_publishes_a_pending_answer_before_its_question(self):
        # Arrange: the first answer succeeds but never reaches the chat
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "Question A")
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(FakeProvider([text_turn("Answer A")]), first.recorder).run(
                "Question A"
            )

        # Act
        chat.prepare_turn(self.conversation, "Question B")
        representation = chat.representation(self.conversation)

        # Assert: the recovered answer belongs to the question it answered
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["Question A", "Answer A", "Question B"],
        )

    def test_publication_refuses_an_answer_a_replacement_already_published(self):
        # Arrange: a regeneration publishes while the original is still pending,
        # so a repair scan taken beforehand still holds a stale verdict on it
        chat = AgentChatService()
        original = chat.prepare_turn(self.conversation, "Question")
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(FakeProvider([text_turn("Stale answer")]), original.recorder).run(
                "Question"
            )
        regeneration = chat.prepare_retry(original.execution, regenerate=True)
        agent(FakeProvider([text_turn("Better answer")]), regeneration.recorder).run(
            "Question"
        )
        original.execution.refresh_from_db()

        # Act
        published = DatabaseAgentRecorder(original.execution).publish_assistant_output()

        # Assert: the lock, not the caller's snapshot, settles supersession
        self.assertFalse(published)
        self.assertEqual(
            [
                message["content"]
                for message in chat.representation(self.conversation)["messages"]
            ],
            ["Question", "Better answer"],
        )

    def test_repair_failure_leaves_a_new_turn_writable(self):
        # Arrange: the answer stays pending, then its repair fails at the
        # database level inside the transaction prepare_turn holds
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "Question A")
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(FakeProvider([text_turn("Answer A")]), first.recorder).run(
                "Question A"
            )

        def failing_publish(self, text=None):
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM table_that_does_not_exist")

        # Act
        with patch.object(
            DatabaseAgentRecorder, "publish_assistant_output", failing_publish
        ):
            prepared = chat.prepare_turn(self.conversation, "Question B")

        # Assert: the swallowed database error did not break the enclosing write
        self.assertIsNotNone(prepared.human_message)
        self.assertEqual(
            [
                message["content"]
                for message in chat.representation(self.conversation)["messages"]
            ],
            ["Question A", "Question B", "Answer A"],
        )

    def test_retry_of_a_turn_the_conversation_moved_past_is_refused(self):
        # Arrange: a second turn answers after the first one already did
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "First question")
        agent(FakeProvider([text_turn("First answer")]), first.recorder).run(
            "First question"
        )
        second = chat.prepare_turn(self.conversation, "Second question")
        agent(FakeProvider([text_turn("Second answer")]), second.recorder).run(
            "Second question"
        )

        # Act / Assert: either retry would make the stale branch canonical
        with self.assertRaises(AgentStaleRetryError):
            chat.prepare_retry(first.execution)
        with self.assertRaises(AgentStaleRetryError):
            chat.prepare_retry(first.execution, regenerate=True)

        # The refusal costs nothing: the next turn still sees both exchanges
        self.assertEqual(self.conversation.executions.count(), 2)
        third = chat.prepare_turn(self.conversation, "Third question")
        self.assertEqual(
            [
                block.text
                for message in third.context
                for block in message.content
                if isinstance(block, TextBlock)
            ],
            ["First question", "First answer", "Second question", "Second answer"],
        )

    def test_a_cancelled_run_cannot_append_context_after_its_calls_are_sealed(self):
        # Arrange: a run records a tool call, then another process cancels it
        # while its worker is still dispatching that call
        chat = AgentChatService()
        stopped = chat.prepare_turn(self.conversation, "Interrupted question")
        stopped.recorder.record_message(
            Message(role="user", content=[TextBlock(text="Interrupted question")])
        )
        stopped.recorder.record_message(
            Message(
                role="assistant",
                content=[ToolUseBlock(id="call-1", name="lookup", input={})],
            )
        )
        AgentExecution.objects.filter(id=stopped.execution.id).update(
            status=AgentExecution.Status.CANCELLED
        )
        resumed = chat.prepare_turn(self.conversation, "Next question")

        # Act: the worker returns with the result the seal already stood in for
        with self.assertRaises(InterruptedError):
            stopped.recorder.record_message(
                Message(
                    role="user",
                    content=[
                        ToolResultBlock(
                            tool_use_id="call-1",
                            content={"type": "text", "text": "late result"},
                            is_error=False,
                        )
                    ],
                )
            )

        # Assert: one call still has exactly one result
        answered = [
            block.tool_use_id
            for message in chat.contexts.reconstruct(resumed.execution)
            for block in message.content
            if isinstance(block, ToolResultBlock)
        ]
        self.assertEqual(answered, ["call-1"])

    def test_representation_keeps_polling_for_an_answer_it_could_not_carry(self):
        # Arrange: the answer stays pending, then a worker publishes it after
        # the chat rows are read -- the skew a second connection opens between
        # two queries of one response
        chat = AgentChatService()
        prepared = chat.prepare_turn(self.conversation, "Question")
        with patch.object(
            DatabaseAgentRecorder,
            "publish_assistant_output",
            side_effect=IntegrityError("chat insert failed"),
        ):
            agent(FakeProvider([text_turn("Answer")]), prepared.recorder).run(
                "Question"
            )
        stale_rows = list(self.conversation.chat_messages.order_by("sequence"))
        prepared.execution.refresh_from_db()
        DatabaseAgentRecorder(prepared.execution).publish_assistant_output()

        # Act
        with patch.object(
            AgentConversation, "chat_messages", ChatMessageSnapshot(stale_rows)
        ):
            representation = chat.representation(self.conversation)

        # Assert: an answer this response omits is never reported as delivered
        self.assertEqual(
            [message["content"] for message in representation["messages"]], ["Question"]
        )
        self.assertTrue(representation["executions"][0]["assistant_message_pending"])
