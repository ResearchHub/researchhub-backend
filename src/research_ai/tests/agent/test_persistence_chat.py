"""User-facing chat preparation, retry, publication, and repair coverage."""

import json
from unittest.mock import patch

from django.db import IntegrityError

from research_ai.models import AgentExecution, AgentExecutionMessage
from research_ai.services.agent.tools import Tool
from research_ai.services.agent.types import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from research_ai.services.agent_persistence import (
    AgentChatService,
    AgentConversationBusyError,
    AgentConversationService,
    AgentExecutionService,
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

        # Assert
        self.assertNotIn("secret token", json.dumps(representation))
        self.assertEqual(
            representation["executions"][0]["error"],
            {
                "code": "agent_failed",
                "message": "The agent could not complete this request.",
            },
        )

    def test_public_representation_fetches_assistant_links_without_n_plus_one(self):
        # Arrange
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "First")
        agent(FakeProvider([text_turn("First answer")]), first.recorder).run("First")
        second = chat.prepare_turn(self.conversation, "Second")
        agent(FakeProvider([text_turn("Second answer")]), second.recorder).run("Second")

        # Act / Assert
        with self.assertNumQueries(3):
            representation = chat.representation(self.conversation)
        self.assertEqual(len(representation["executions"]), 2)

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

    def test_prepare_turn_does_not_start_when_context_reconstruction_fails(self):
        # Arrange
        chat = AgentChatService()
        first = chat.prepare_turn(self.conversation, "First")
        agent(FakeProvider([text_turn("Answer")]), first.recorder).run("First")
        message_count = self.conversation.chat_messages.count()
        execution_count = self.conversation.executions.count()

        # Act / Assert
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
        self.assertFalse(
            self.conversation.executions.filter(
                status__in=[
                    AgentExecution.Status.PENDING,
                    AgentExecution.Status.RUNNING,
                ]
            ).exists()
        )

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

    def test_regeneration_supersedes_an_answer_that_never_published(self):
        # Arrange: the original succeeds but its chat publication fails
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

        # Act: the user regenerates before any read repairs the original
        regeneration = chat.prepare_retry(original.execution, regenerate=True)
        agent(FakeProvider([text_turn("Better answer")]), regeneration.recorder).run(
            "Question"
        )
        representation = chat.representation(self.conversation)

        # Assert
        self.assertEqual(
            [message["content"] for message in representation["messages"]],
            ["Question", "Better answer"],
        )
        superseded = next(
            item
            for item in representation["executions"]
            if item["id"] == original.execution.id
        )
        self.assertFalse(superseded["assistant_message_pending"])

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
