"""Conversation, context, run-detail, and retention service coverage."""

from unittest.mock import patch

from django.db import IntegrityError, transaction

from note.models import Note
from research_ai.models import (
    AgentContextMessage,
    AgentConversation,
    AgentExecution,
    AgentExecutionMessage,
    NoteAgentConversation,
)
from research_ai.services.agent.types import (
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from research_ai.services.agent_persistence import (
    AgentChatService,
    AgentContextService,
    AgentConversationService,
    AgentExecutionService,
    AgentRetentionService,
    AgentRunDetailsService,
    NoteAgentConversationService,
)
from research_ai.tests.agent.persistence_test_helpers import (
    AgentPersistenceTestCase,
    FakeProvider,
    agent,
    text_turn,
)
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import NOTE


class AgentPersistenceServiceTests(AgentPersistenceTestCase):
    def test_note_attachment_is_idempotent_and_queryable(self):
        # Arrange
        note = Note.objects.create(
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type=NOTE
            )
        )
        second_conversation = AgentConversationService().create(
            workflow="notebook_chat",
        )
        service = NoteAgentConversationService()

        # Act
        first_link = service.attach(self.conversation, note)
        repeated_link = service.attach(self.conversation, note)
        service.attach(second_conversation, note)

        # Assert
        self.assertEqual(first_link, repeated_link)
        self.assertEqual(NoteAgentConversation.objects.count(), 2)
        self.assertEqual(
            set(service.for_note(note).values_list("id", flat=True)),
            {self.conversation.id, second_conversation.id},
        )

    def test_note_attachment_failure_does_not_break_surrounding_transaction(self):
        # Arrange
        note = Note.objects.create(
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type=NOTE
            )
        )
        service = NoteAgentConversationService()
        service.attach(self.conversation, note)

        def violate_unique(**_kwargs):
            return NoteAgentConversation.objects.create(
                note=note,
                conversation=self.conversation,
            )

        # Act
        with transaction.atomic():
            with (
                patch.object(
                    NoteAgentConversation.objects,
                    "get_or_create",
                    side_effect=violate_unique,
                ),
                self.assertRaises(IntegrityError),
            ):
                service.attach(self.conversation, note)
            surviving = AgentConversation.objects.create()

        # Assert
        self.assertTrue(AgentConversation.objects.filter(id=surviving.id).exists())

    def test_debug_retention_does_not_delete_chat(self):
        # Arrange
        human_message = AgentConversationService().add_human_message(
            self.conversation, "Keep me"
        )
        recorder = AgentExecutionService().start(
            self.conversation,
            trigger_message=human_message,
            initial_prompt_provenance=AgentExecutionMessage.Provenance.HUMAN,
            publish_assistant_message=True,
        )
        agent(FakeProvider([text_turn("Keep me too")]), recorder).run("Keep me")

        # Act
        AgentRetentionService().delete_conversation_debug(self.conversation)

        # Assert
        execution = self.conversation.executions.get()
        self.assertEqual(execution.messages.count(), 0)
        self.assertEqual(execution.context_messages.count(), 2)
        rebuilt = AgentContextService().reconstruct(execution)
        self.assertEqual(
            [message.content[0].text for message in rebuilt],
            ["Keep me", "Keep me too"],
        )
        self.assertEqual(
            list(
                self.conversation.chat_messages.order_by("sequence").values_list(
                    "content", flat=True
                )
            ),
            ["Keep me", "Keep me too"],
        )
        self.assertEqual(AgentExecutionMessage.objects.count(), 0)
        self.assertEqual(AgentContextMessage.objects.count(), 2)

    def test_context_reconstruction_orders_messages_across_executions(self):
        # Arrange
        provider_state = {"anthropic": {"container": {"id": "container_123"}}}
        first_recorder = self.recorder(
            initial_prompt_provenance=AgentExecutionMessage.Provenance.HUMAN
        )
        agent(
            FakeProvider([text_turn("first answer", provider_state=provider_state)]),
            first_recorder,
        ).run("first question")
        first = AgentExecution.objects.get(id=first_recorder.execution.id)
        prior_context = AgentContextService().reconstruct(first)
        second_recorder = self.recorder(
            context_parent=first,
            initial_prompt_provenance=AgentExecutionMessage.Provenance.HUMAN,
        )

        # Act
        agent(
            FakeProvider([text_turn("second answer")]), second_recorder
        ).continue_conversation(prior_context, "follow up")
        second = AgentExecution.objects.get(id=second_recorder.execution.id)
        rebuilt = AgentContextService().reconstruct(second)

        # Assert
        self.assertEqual(
            [message.content[0].text for message in rebuilt],
            ["first question", "first answer", "follow up", "second answer"],
        )
        self.assertEqual(rebuilt[1].provider_state, provider_state)
        self.assertEqual(
            list(
                self.conversation.trace_messages.order_by("sequence").values_list(
                    "sequence", flat=True
                )
            ),
            [1, 2, 3, 4],
        )

    def _terminated_run(self, status, prompt, answer, *, context_parent=None):
        """Run an execution to completion, then force it into ``status``."""
        recorder = self.recorder(
            context_parent=context_parent,
            initial_prompt_provenance=AgentExecutionMessage.Provenance.HUMAN,
        )
        agent(FakeProvider([text_turn(answer)]), recorder).run(prompt)
        AgentExecution.objects.filter(id=recorder.execution.id).update(status=status)
        return AgentExecution.objects.get(id=recorder.execution.id)

    def test_continuation_ignores_unfinished_runs_by_default(self):
        # Arrange
        succeeded = self._terminated_run(
            AgentExecution.Status.SUCCEEDED, "first question", "first answer"
        )
        self._terminated_run(
            AgentExecution.Status.FAILED,
            "second question",
            "second answer",
            context_parent=succeeded,
        )

        # Act
        rebuilt = AgentContextService().for_continuation(self.conversation)

        # Assert
        self.assertEqual(
            [message.content[0].text for message in rebuilt],
            ["first question", "first answer"],
        )

    def test_continuation_resumes_cancelled_runs_when_partial(self):
        # Arrange: a cancelled run is the latest attempt, so skipping it would
        # silently fall back to the succeeded one and lose the human prompt.
        succeeded = self._terminated_run(
            AgentExecution.Status.SUCCEEDED, "first question", "first answer"
        )
        self._terminated_run(
            AgentExecution.Status.CANCELLED,
            "cancelled question",
            "partial answer",
            context_parent=succeeded,
        )

        # Act
        rebuilt = AgentContextService().for_continuation(
            self.conversation, include_partial=True
        )

        # Assert
        self.assertEqual(
            [message.content[0].text for message in rebuilt],
            [
                "first question",
                "first answer",
                "cancelled question",
                "partial answer",
            ],
        )

    def test_cancel_pending_prevents_claim_without_exposing_an_error(self):
        # Arrange
        chat = AgentChatService()
        queued = chat.prepare_queued_turn(self.conversation, "Queued question")
        service = AgentExecutionService()

        # Act
        cancelled = service.cancel(queued.execution)
        claim = chat.claim_turn(queued.execution)
        representation = chat.representation(self.conversation)

        # Assert
        self.assertTrue(cancelled)
        self.assertIsNone(claim)
        queued.execution.refresh_from_db()
        self.assertEqual(queued.execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(queued.execution.stop_reason, "cancelled")
        self.assertIsNotNone(queued.execution.finished_at)
        self.assertIsNotNone(queued.execution.last_activity_at)
        self.assertIsNone(representation["executions"][0]["error"])

    def test_cancel_running_interrupts_the_next_context_write(self):
        # Arrange
        recorder = self.recorder()
        recorder.record_message(
            Message(role="user", content=[TextBlock(text="Question")])
        )
        service = AgentExecutionService()

        # Act
        cancelled = service.cancel(recorder.execution)
        with self.assertRaises(InterruptedError):
            recorder.record_message(
                Message(role="assistant", content=[TextBlock(text="Late answer")])
            )
        recorder.on_run_failed(InterruptedError("cancel observed"))

        # Assert
        self.assertTrue(cancelled)
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(execution.stop_reason, "cancelled")
        self.assertEqual(execution.context_messages.count(), 1)

    def test_cancel_terminal_execution_returns_false(self):
        # Arrange
        recorder = self.recorder()
        agent(FakeProvider([text_turn("Answer")]), recorder).run("Question")

        # Act
        cancelled = AgentExecutionService().cancel(recorder.execution)

        # Assert
        self.assertFalse(cancelled)
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertNotEqual(execution.stop_reason, "cancelled")

    def test_follow_up_queued_turn_resumes_cancelled_context_with_a_seal(self):
        # Arrange
        chat = AgentChatService()
        queued = chat.prepare_queued_turn(self.conversation, "First question")
        claimed = chat.claim_turn(queued.execution)
        self.assertIsNotNone(claimed)
        claimed.recorder.record_message(
            Message(role="user", content=[TextBlock(text="First question")])
        )
        claimed.recorder.record_message(
            Message(
                role="assistant",
                content=[ToolUseBlock(id="call-1", name="lookup", input={})],
            )
        )
        AgentExecutionService().cancel(claimed.execution)

        # Act
        follow_up = chat.prepare_queued_turn(self.conversation, "Second question")
        prepared = chat.claim_turn(follow_up.execution)

        # Assert
        self.assertIsNotNone(prepared)
        self.assertEqual(follow_up.execution.context_parent_id, claimed.execution.id)
        self.assertEqual(
            [
                block.tool_use_id
                for message in prepared.context
                for block in message.content
                if isinstance(block, ToolResultBlock)
            ],
            ["call-1"],
        )

    def test_continuation_without_terminal_runs_is_empty(self):
        # Arrange
        self.recorder()

        # Act
        rebuilt = AgentContextService().for_continuation(
            self.conversation, include_partial=True
        )

        # Assert
        self.assertEqual(rebuilt, [])

    def test_run_details_reports_metrics_and_a_failure_only_when_one_exists(self):
        # Arrange: one run that answered and one that never did
        recorder = self.recorder()
        agent(FakeProvider([text_turn("done", latency_ms=23)]), recorder).run(
            "question"
        )
        answered = AgentExecution.objects.get(id=recorder.execution.id)
        broken = AgentExecutionService().start(self.conversation).execution
        AgentExecution.objects.filter(id=broken.id).update(
            status=AgentExecution.Status.FAILED,
            error_type="ProviderError",
            error_message="provider unavailable",
            error_details={"cause_type": "TimeoutError"},
        )

        # Act
        service = AgentRunDetailsService()
        answered_details = service.get(answered)
        broken_details = service.get(AgentExecution.objects.get(id=broken.id))

        # Assert
        self.assertEqual(answered_details.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(answered_details.stop_reason, StopReason.END_TURN)
        self.assertEqual(answered_details.total_latency_ms, 23)
        self.assertEqual(len(answered_details.trace), 2)
        self.assertEqual(answered_details.trace[-1].latency_ms, 23)
        self.assertIsNone(answered_details.failure)
        self.assertEqual(
            (
                broken_details.failure.type,
                broken_details.failure.message,
                broken_details.failure.details,
            ),
            ("ProviderError", "provider unavailable", {"cause_type": "TimeoutError"}),
        )
