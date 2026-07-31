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
from research_ai.services.agent.types import StopReason
from research_ai.services.agent_persistence import (
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

    def test_run_details_exposes_metrics_and_trace(self):
        # Arrange
        recorder = self.recorder()
        agent(FakeProvider([text_turn("done", latency_ms=23)]), recorder).run(
            "question"
        )
        execution = AgentExecution.objects.get(id=recorder.execution.id)

        # Act
        details = AgentRunDetailsService().get(execution)

        # Assert
        self.assertEqual(details["status"], AgentExecution.Status.SUCCEEDED)
        self.assertEqual(details["stop_reason"], StopReason.END_TURN)
        self.assertEqual(details["total_latency_ms"], 23)
        self.assertEqual(len(details["trace"]), 2)
