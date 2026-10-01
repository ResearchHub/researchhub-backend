from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from note.tests.helpers import create_note
from research_ai.models import AgentExecution, AgentFile
from research_ai.services.agent_files import AgentFileError
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)
from research_ai.tests.agent_files.helpers import make_file
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument

MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}
PDF_TEXT = (
    "[Page 1]\nAim 1: map enhancers.\n\n[Page 2]\nBudget: $50,000 for sequencing."
)


def _make_service(provider=None):
    return NotebookChatService(
        provider=provider,
        oa_client=Mock(),
        web_search_client=Mock(configured=False),
    )


@override_settings(**MODEL_SETTINGS)
class NotebookChatAttachmentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.note, _content = create_note(self.user, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.user,
        )
        self.service = _make_service()
        self.conversation = self.service.create_conversation(self.note, self.user)
        self.file = make_file(self.user, text=PDF_TEXT, page_count=2)

    def _submit(self, text, **kwargs):
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return self.service.submit_message(
                self.note, self.conversation, text, **kwargs
            )

    def _finish(self, execution, *turns):
        provider = FakeProvider(list(turns))
        result = _make_service(provider=provider).run_turn(execution.id)
        self.assertNotIn("error", result)
        return provider

    def test_sent_files_open_the_turn_prompt_and_can_be_read(self):
        # Arrange
        execution = self._submit("What are the aims?", file_ids=[self.file.id])

        # Act
        provider = self._finish(
            execution,
            tool_turn("t1", "read_attachment", {"attachment_id": self.file.id}),
            text_turn("Aim 1 maps enhancers."),
        )

        # Assert
        prompt = provider.calls[0][-1].content[0].text
        self.assertEqual(
            prompt,
            "[The user attached these files to this message. Read them with "
            "read_attachment, or find passages with search_attachment:\n"
            f'- attachment {self.file.id}: "grant.pdf" (PDF, 2 pages, '
            f"{len(PDF_TEXT)} characters)]\n\nWhat are the aims?",
        )
        read = provider.calls[1][-1].content[0].content
        self.assertEqual(read["text"], PDF_TEXT)
        # The chat shows the user's own words with the file beside them.
        (message,) = [
            message
            for message in self.service.representation(self.conversation)["messages"]
            if message["role"] == "user"
        ]
        self.assertEqual(message["content"], "What are the aims?")
        self.assertEqual(
            [attachment["id"] for attachment in message["attachments"]],
            [self.file.id],
        )

    def test_files_sent_earlier_stay_searchable_in_later_turns(self):
        # Arrange
        first = self._submit("Read this", file_ids=[self.file.id])
        self._finish(first, text_turn("Read it."))
        second = self._submit("What is the budget?")

        # Act
        provider = self._finish(
            second,
            tool_turn("t1", "search_attachment", {"query": "budget sequencing"}),
            text_turn("$50,000."),
        )

        # Assert: no new files, so no new manifest; the old file is in scope.
        self.assertEqual(provider.calls[0][-1].content[0].text, "What is the budget?")
        passages = provider.calls[1][-1].content[0].content["passages"]
        self.assertEqual(passages[0]["attachment_id"], self.file.id)
        self.assertIn("$50,000", passages[0]["text"])

    def test_a_file_that_cannot_be_sent_rejects_the_whole_message(self):
        # Arrange
        failed = make_file(self.user, status=AgentFile.Status.FAILED, error="Bad.")

        # Act
        with self.assertRaises(AgentFileError):
            self._submit("Use both", file_ids=[self.file.id, failed.id])

        # Assert
        self.assertFalse(self.conversation.chat_messages.exists())
        self.assertFalse(AgentExecution.objects.exists())
        self.file.refresh_from_db()
        self.assertIsNone(self.file.message_id)
