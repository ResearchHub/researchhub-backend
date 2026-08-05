from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.tests.helpers import create_note
from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.agent_persistence import AgentConversationBusyError
from research_ai.services.notebook_chat import WORKFLOW, NotebookChatService
from research_ai.services.notebook_chat.config import NotebookChatConfig
from research_ai.tests.agent.persistence_test_helpers import (
    FakeProvider,
    text_turn,
    tool_turn,
)
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument

EDITED_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Edited by the assistant"}],
        }
    ],
}


def _make_service(provider=None, **kwargs):
    return NotebookChatService(
        provider=provider,
        oa_client=Mock(),
        web_search_client=Mock(configured=False),
        **kwargs,
    )


class NotebookChatServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.note, self.content = create_note(self.user, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.user,
        )
        self.service = _make_service()

    def _submit(self, text="Please add a summary."):
        with (
            patch("research_ai.tasks.run_notebook_chat_turn_task.delay") as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            execution = self.service.submit_message(self.note, self.user, text)
        return execution, delay

    def test_submit_message_prepares_turn_and_schedules_task(self):
        # Act
        execution, delay = self._submit()

        # Assert
        conversation = execution.conversation
        self.assertEqual(conversation.workflow, WORKFLOW)
        self.assertEqual(conversation.user, self.user)
        self.assertTrue(conversation.note_links.filter(note=self.note).exists())
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)
        self.assertIn(str(self.note.id), execution.system_prompt)
        self.assertIn(self.note.title, execution.system_prompt)
        self.assertEqual(execution.configuration["note_id"], self.note.id)
        self.assertEqual(execution.trigger_message.content, "Please add a summary.")
        delay.assert_called_once_with(execution.id)

    def test_submit_message_reuses_the_users_conversation_on_the_note(self):
        # Arrange
        first, _delay = self._submit()
        first.status = AgentExecution.Status.SUCCEEDED
        first.save(update_fields=["status"])

        # Act
        second, _delay = self._submit("Another request")

        # Assert
        self.assertEqual(second.conversation_id, first.conversation_id)
        self.assertEqual(second.context_parent_id, first.id)

    def test_submit_message_rejects_empty_and_oversized_messages(self):
        # Arrange
        service = _make_service(config=NotebookChatConfig(max_message_chars=10))

        # Act & Assert
        with self.assertRaises(ValueError):
            service.submit_message(self.note, self.user, "   ")
        with self.assertRaises(ValueError):
            service.submit_message(self.note, self.user, "x" * 11)

    def test_first_message_race_reuses_the_concurrently_created_conversation(self):
        # Arrange: another request created the conversation after this
        # request's unlocked pre-check ran empty; the re-check under the note
        # lock must pick it up instead of creating a duplicate.
        existing = self.service.get_or_create_conversation(self.note, self.user)
        with patch.object(
            NotebookChatService, "get_conversation", side_effect=[None, existing]
        ):
            # Act
            conversation = self.service.get_or_create_conversation(self.note, self.user)

        # Assert
        self.assertEqual(conversation.id, existing.id)
        self.assertEqual(AgentConversation.objects.count(), 1)

    def test_submit_message_while_turn_is_running_raises_busy(self):
        # Arrange
        self._submit()

        # Act & Assert
        with self.assertRaises(AgentConversationBusyError):
            self.service.submit_message(self.note, self.user, "again")

    def test_run_turn_edits_note_and_publishes_reply(self):
        # Arrange
        execution, _delay = self._submit("Replace the note body.")
        provider = FakeProvider(
            [
                tool_turn("t1", "read_note", {"note_id": self.note.id}),
                tool_turn(
                    "t2",
                    "edit_note",
                    {
                        "note_id": self.note.id,
                        "expected_version_id": self.content.id,
                        "content": EDITED_DOC,
                    },
                ),
                text_turn("I replaced the note body."),
            ]
        )
        service = _make_service(provider=provider)

        # Act
        result = service.run_turn(execution.id)

        # Assert
        execution.refresh_from_db()
        self.note.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.SUCCEEDED)
        self.assertEqual(result["final_text"], "I replaced the note body.")
        self.assertEqual(self.note.latest_version.json, EDITED_DOC)
        reply = execution.generated_chat_message
        self.assertIsNotNone(reply)
        self.assertEqual(reply.content, "I replaced the note body.")
        # The user prompt the model saw is the chat message, not a wrapper.
        first_call = provider.calls[0]
        self.assertEqual(first_call[0].content[0].text, "Replace the note body.")

    def test_run_turn_refuses_notes_outside_the_conversation(self):
        # Arrange: a second note the same user administers; the model tries
        # to read it from this note's chat.
        other_note, _other_content = create_note(self.user, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=other_note.unified_document.id,
            user=self.user,
        )
        execution, _delay = self._submit("Summarize my other note.")
        provider = FakeProvider(
            [
                tool_turn("t1", "read_note", {"note_id": other_note.id}),
                text_turn("Done."),
            ]
        )
        service = _make_service(provider=provider)

        # Act
        service.run_turn(execution.id)

        # Assert: the tool refused, so the other note never reached the model.
        tool_results = [
            block
            for message in provider.calls[1]
            for block in message.content
            if getattr(block, "type", "") == "tool_result"
        ]
        self.assertEqual(len(tool_results), 1)
        self.assertIn("not found or not accessible", tool_results[0].content["error"])

    def test_run_turn_provider_failure_marks_execution_failed(self):
        # Arrange
        execution, _delay = self._submit()
        provider = FakeProvider([RuntimeError("provider exploded")])
        service = _make_service(provider=provider)

        # Act
        result = service.run_turn(execution.id)

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertIn("provider exploded", result["error"])

    def test_run_turn_skips_execution_that_is_not_running(self):
        # Arrange
        execution, _delay = self._submit()
        AgentExecution.objects.filter(id=execution.id).update(
            status=AgentExecution.Status.CANCELLED
        )

        # Act
        result = self.service.run_turn(execution.id)

        # Assert
        self.assertTrue(result["skipped"])
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertEqual(result["execution_id"], execution.id)

    def test_run_turn_without_note_link_fails_the_execution(self):
        # Arrange
        execution, _delay = self._submit()
        execution.conversation.note_links.all().delete()

        # Act
        result = self.service.run_turn(execution.id)

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertIn("missing", result["error"])

    def test_second_turn_carries_prior_context(self):
        # Arrange: complete a first turn, then run a second one.
        first, _delay = self._submit("First question")
        service = _make_service(provider=FakeProvider([text_turn("First answer")]))
        service.run_turn(first.id)

        second, _delay = self._submit("Second question")
        provider = FakeProvider([text_turn("Second answer")])
        service = _make_service(provider=provider)

        # Act
        service.run_turn(second.id)

        # Assert: the model's context contains the first exchange.
        sent = provider.calls[0]
        texts = [
            block.text
            for message in sent
            for block in message.content
            if hasattr(block, "text")
        ]
        self.assertIn("First question", texts)
        self.assertIn("First answer", texts)
        self.assertIn("Second question", texts)
        self.assertEqual(AgentConversation.objects.filter(user=self.user).count(), 1)
