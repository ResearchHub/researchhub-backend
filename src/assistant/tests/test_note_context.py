from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from assistant.models import AssistantSession
from assistant.services.bedrock_chat_service import BedrockChatService
from note.related_models.note_model import Note, NoteContent
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User


class NoteContextTestCase(TestCase):
    """Tests for note content injection into Bedrock calls."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="notetester",
            email="notetester@test.com",
            password="testpassword123",
        )
        self.session = AssistantSession(
            user=self.user,
            role="funder",
        )
        self.session.initialize_field_state()
        self.session.save()

    def _create_note_with_content(self, plain_text="Initial draft content"):
        """Helper to create a Note with a NoteContent version."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION",
        )
        note = Note.objects.create(
            created_by=self.user,
            unified_document=unified_doc,
            title="Test Note",
        )
        note_content = NoteContent.objects.create(
            note=note,
            plain_text=plain_text,
        )
        note.latest_version = note_content
        note.save()
        return note, note_content

    @patch("assistant.services.bedrock_chat_service.create_client")
    @override_settings(ASSISTANT_ENABLED=True)
    def test_chat_service_skips_note_when_no_note_id(self, mock_create_client):
        """When session has no note_id, no note content is fetched."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": "Response text.\n\n<structured>"
                            '{"input_type": null, "editor_field": null, '
                            '"quick_replies": null, "field_updates": null, '
                            '"follow_up": null}'
                            "</structured>"
                        }
                    ]
                }
            }
        }
        mock_create_client.return_value = mock_client

        service = BedrockChatService()
        service.process_message(self.session, "What's a good budget?")

        # Verify the system prompt does NOT contain document draft section
        call_args = mock_client.converse.call_args
        system_prompt = call_args.kwargs["system"][0]["text"]
        self.assertNotIn("CURRENT DOCUMENT DRAFT", system_prompt)

    @patch("assistant.services.bedrock_chat_service.create_client")
    @override_settings(ASSISTANT_ENABLED=True)
    def test_chat_service_sends_note_on_first_message_with_note(
        self, mock_create_client
    ):
        """When note_id is set but last_seen_note_content_id is null, send the note."""
        note, note_content = self._create_note_with_content(
            "This is the initial RFP draft about AI safety research."
        )
        self.session.note_id = note.id
        self.session.save()

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": "I see your draft.\n\n<structured>"
                            '{"input_type": null, "editor_field": null, '
                            '"quick_replies": null, "field_updates": null, '
                            '"follow_up": null}'
                            "</structured>"
                        }
                    ]
                }
            }
        }
        mock_create_client.return_value = mock_client

        service = BedrockChatService()
        service.process_message(self.session, "Can you review my draft?")

        # Verify the system prompt DOES contain the document draft
        call_args = mock_client.converse.call_args
        system_prompt = call_args.kwargs["system"][0]["text"]
        self.assertIn("CURRENT DOCUMENT DRAFT", system_prompt)
        self.assertIn("AI safety research", system_prompt)

        # Verify last_seen_note_content_id was updated
        self.session.refresh_from_db()
        self.assertEqual(self.session.last_seen_note_content_id, note_content.id)

    @patch("assistant.services.bedrock_chat_service.create_client")
    @override_settings(ASSISTANT_ENABLED=True)
    def test_chat_service_sends_note_to_bedrock_if_note_has_changed(
        self, mock_create_client
    ):
        """When the note has a new version, send the updated content."""
        note, old_content = self._create_note_with_content("Old draft version.")

        self.session.note_id = note.id
        self.session.last_seen_note_content_id = old_content.id
        self.session.save()

        # Create a new version (simulating user edit in editor)
        new_content = NoteContent.objects.create(
            note=note,
            plain_text="Updated draft with new background section about climate change.",
        )
        note.latest_version = new_content
        note.save()

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": "I see the changes.\n\n<structured>"
                            '{"input_type": null, "editor_field": null, '
                            '"quick_replies": null, "field_updates": null, '
                            '"follow_up": null}'
                            "</structured>"
                        }
                    ]
                }
            }
        }
        mock_create_client.return_value = mock_client

        service = BedrockChatService()
        service.process_message(self.session, "I updated the background section.")

        # Verify the system prompt contains the NEW content
        call_args = mock_client.converse.call_args
        system_prompt = call_args.kwargs["system"][0]["text"]
        self.assertIn("CURRENT DOCUMENT DRAFT", system_prompt)
        self.assertIn("climate change", system_prompt)
        self.assertNotIn("Old draft version", system_prompt)

        # Verify last_seen_note_content_id was updated to new version
        self.session.refresh_from_db()
        self.assertEqual(self.session.last_seen_note_content_id, new_content.id)

    @patch("assistant.services.bedrock_chat_service.create_client")
    @override_settings(ASSISTANT_ENABLED=True)
    def test_chat_service_does_not_send_note_to_bedrock_if_note_has_not_changed(
        self, mock_create_client
    ):
        """When the note version hasn't changed, don't inject the document."""
        note, note_content = self._create_note_with_content("Same old draft.")

        self.session.note_id = note.id
        self.session.last_seen_note_content_id = note_content.id  # Already seen
        self.session.save()

        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": "Budget response.\n\n<structured>"
                            '{"input_type": null, "editor_field": null, '
                            '"quick_replies": null, "field_updates": null, '
                            '"follow_up": null}'
                            "</structured>"
                        }
                    ]
                }
            }
        }
        mock_create_client.return_value = mock_client

        service = BedrockChatService()
        service.process_message(self.session, "What's a good budget?")

        # Verify the system prompt does NOT contain the document draft
        call_args = mock_client.converse.call_args
        system_prompt = call_args.kwargs["system"][0]["text"]
        self.assertNotIn("CURRENT DOCUMENT DRAFT", system_prompt)
        self.assertNotIn("Same old draft", system_prompt)

        # last_seen_note_content_id should remain unchanged
        self.session.refresh_from_db()
        self.assertEqual(self.session.last_seen_note_content_id, note_content.id)
