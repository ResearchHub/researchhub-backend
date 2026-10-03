"""Unit tests for research_ai models."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from research_ai.models import (
    AgentConversation,
    AgentExecution,
    AgentExecutionMessage,
    Expert,
    OutreachMailboxConnection,
    is_allowed_outreach_mailbox_email,
    normalize_outreach_mailbox_email,
)


class ExpertOrcidTests(SimpleTestCase):
    def test_orcid_from_sources(self):
        # Arrange
        expert = Expert(
            sources=[
                {"text": "ORCID", "url": "https://orcid.org/0000-0002-1825-0097"},
            ]
        )
        # Act
        orcid = expert.orcid
        # Assert
        self.assertEqual(orcid, "0000-0002-1825-0097")

    def test_orcid_handles_plain_string_sources_and_misses(self):
        # Arrange
        expert = Expert(sources=["https://example.edu/jane", "not a url"])
        # Act
        orcid = expert.orcid
        # Assert
        self.assertIsNone(orcid)


class OutreachMailboxEmailAllowlistTests(SimpleTestCase):
    def test_normalize_strips_and_lowercases(self):
        # Arrange / Act / Assert
        self.assertEqual(
            normalize_outreach_mailbox_email("  Jane.Doe@Gmail.COM "),
            "jane.doe@gmail.com",
        )

    def test_gmail_and_googlemail_accepted(self):
        # Arrange / Act / Assert
        self.assertTrue(is_allowed_outreach_mailbox_email("editor@gmail.com"))
        self.assertTrue(is_allowed_outreach_mailbox_email("Editor@GoogleMail.com"))

    def test_researchhub_and_workspace_rejected(self):
        # Arrange / Act / Assert
        self.assertFalse(
            is_allowed_outreach_mailbox_email("user@researchhub.foundation")
        )
        self.assertFalse(is_allowed_outreach_mailbox_email("user@researchhub.com"))
        self.assertFalse(
            is_allowed_outreach_mailbox_email("editor@company.workspace.google")
        )

    def test_clean_rejects_non_gmail(self):
        # Arrange
        connection = OutreachMailboxConnection(
            email="user@researchhub.foundation",
        )
        # Act / Assert
        with self.assertRaises(ValidationError) as ctx:
            connection.clean()
        self.assertIn("email", ctx.exception.message_dict)


class AgentExecutionMessageTests(TestCase):
    def test_rejects_conversation_that_does_not_match_execution(self):
        # Arrange
        execution_conversation = AgentConversation.objects.create()
        other_conversation = AgentConversation.objects.create()
        execution = AgentExecution.objects.create(
            conversation=execution_conversation,
            attempt=1,
        )

        # Act / Assert
        with self.assertRaisesMessage(
            ValidationError,
            "Must match the conversation associated with execution.",
        ):
            AgentExecutionMessage.objects.create(
                conversation=other_conversation,
                execution=execution,
                sequence=1,
                execution_sequence=1,
                role="user",
                provenance=AgentExecutionMessage.Provenance.BACKEND,
                content=[],
            )
        self.assertFalse(AgentExecutionMessage.objects.exists())
