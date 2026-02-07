from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from assistant.models import AssistantSession


class ChatActionTestCase(TestCase):
    """Tests for the chat action field (start, resume, message)."""

    def setUp(self):
        from user.models import User

        self.client = APIClient()
        self.user = User.objects.create_user(
            username="actiontester",
            email="actiontester@test.com",
            password="testpassword123",
        )
        self.client.force_authenticate(user=self.user)
        self.session = AssistantSession(
            user=self.user,
            role="funder",
        )
        self.session.initialize_field_state()
        self.session.save()

    @patch("assistant.views.chat_view.BedrockChatService")
    def test_bedrock_bypassed_and_initial_message_returned_when_new(
        self, mock_bedrock_class
    ):
        """action=start returns the initial greeting without calling Bedrock."""
        mock_service = MagicMock()
        mock_service.get_initial_message.return_value = {
            "message": "Hi! I'm here to help you create an effective funding opportunity.",
            "follow_up": None,
            "input_type": None,
            "editor_field": None,
            "quick_replies": [
                {
                    "label": "Start fresh",
                    "value": "I want to start a new RFP from scratch",
                },
            ],
            "field_updates": None,
            "complete": False,
            "payload": None,
        }
        mock_bedrock_class.return_value = mock_service

        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(self.session.id),
                "action": "start",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("funding opportunity", response.data["message"])

        # Bedrock should NOT have been called
        mock_service.process_message.assert_not_called()

        # Initial message should be called
        mock_service.get_initial_message.assert_called_once_with("funder")

        # Message should be in conversation history
        self.session.refresh_from_db()
        self.assertEqual(len(self.session.conversation_history), 1)
        self.assertEqual(self.session.conversation_history[0]["role"], "assistant")

    @patch("assistant.views.chat_view.BedrockChatService")
    def test_bedrock_bypassed_and_resume_message_returned_when_resuming(
        self, mock_bedrock_class
    ):
        """action=resume returns a progress summary without calling Bedrock."""
        # Add some history and field state to simulate an in-progress session
        self.session.add_message("assistant", "Welcome!")
        self.session.add_message("user", "I want to fund AI research")
        self.session.update_field("title", "complete", "AI Research RFP")
        self.session.save()

        mock_service = MagicMock()
        mock_service.get_resume_message.return_value = {
            "message": "Welcome back! You've completed 1 of 3 required fields (title).",
            "follow_up": None,
            "input_type": None,
            "editor_field": None,
            "quick_replies": [
                {
                    "label": "Continue where I left off",
                    "value": "Let's continue where we left off.",
                },
            ],
            "field_updates": None,
            "complete": False,
            "payload": None,
        }
        mock_bedrock_class.return_value = mock_service

        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(self.session.id),
                "action": "resume",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Welcome back", response.data["message"])

        # Bedrock should NOT have been called
        mock_service.process_message.assert_not_called()

        # Resume message should be called
        mock_service.get_resume_message.assert_called_once()

        # Conversation history should NOT have changed (resume doesn't add to history)
        self.session.refresh_from_db()
        self.assertEqual(len(self.session.conversation_history), 2)

    @patch("assistant.views.chat_view.BedrockChatService")
    def test_bedrock_triggered_when_ongoing_conversation(self, mock_bedrock_class):
        """action=message (default) sends the message to Bedrock."""
        mock_service = MagicMock()
        mock_service.process_message.return_value = {
            "message": "Great! What research area is this RFP focused on?",
            "follow_up": None,
            "input_type": None,
            "editor_field": None,
            "quick_replies": None,
            "field_updates": None,
            "complete": False,
            "payload": None,
        }
        mock_bedrock_class.return_value = mock_service

        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(self.session.id),
                "action": "message",
                "message": "I want to fund AI safety research",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Bedrock SHOULD have been called
        mock_service.process_message.assert_called_once()
        call_kwargs = mock_service.process_message.call_args
        self.assertEqual(
            call_kwargs.kwargs["user_message"], "I want to fund AI safety research"
        )

        # start/resume should NOT have been called
        mock_service.get_initial_message.assert_not_called()
        mock_service.get_resume_message.assert_not_called()

    def test_message_required_when_action_is_message(self):
        """action=message without a message returns 400."""
        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(self.session.id),
                "action": "message",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("message", response.data)

    def test_message_not_required_when_action_is_start(self):
        """action=start does not require a message field."""
        with patch("assistant.views.chat_view.BedrockChatService") as mock_bedrock:
            mock_service = MagicMock()
            mock_service.get_initial_message.return_value = {
                "message": "Hi!",
                "follow_up": None,
                "input_type": None,
                "editor_field": None,
                "quick_replies": [],
                "field_updates": None,
                "complete": False,
                "payload": None,
            }
            mock_bedrock.return_value = mock_service

            response = self.client.post(
                "/api/assistant/chat/",
                {
                    "session_id": str(self.session.id),
                    "action": "start",
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_default_action_is_message(self):
        """Omitting action defaults to 'message', which requires a message."""
        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(self.session.id),
                # no action, no message
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
