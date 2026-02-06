from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from assistant.models import AssistantSession


class ChatViewTestCase(TestCase):
    """Tests for the ChatView API endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        from user.models import User

        self.client = APIClient()
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@test.com",
            password="testpassword123",
        )
        self.client.force_authenticate(user=self.user)

    def test_chat_requires_authentication(self):
        """Test that unauthenticated requests are rejected."""
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Hello"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_chat_requires_message(self):
        """Test that message is required."""
        response = self.client.post(
            "/api/assistant/chat/",
            {"role": "researcher"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("message", response.data)

    def test_chat_requires_role_for_new_session(self):
        """Test that role is required when no session_id is provided."""
        response = self.client.post(
            "/api/assistant/chat/",
            {"message": "Hello"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("role", response.data)

    @patch("assistant.views.chat_view.BedrockChatService")
    def test_chat_creates_new_session(self, mock_bedrock_class):
        """Test that a new session is created on first message."""
        # Mock the Bedrock service
        mock_service = MagicMock()
        mock_service.get_initial_message.return_value = {
            "message": "Hello! How can I help?",
            "follow_up": None,
            "input_type": None,
            "quick_replies": [],
            "field_updates": None,
            "complete": False,
            "payload": None,
        }
        mock_service.process_message.return_value = {
            "message": "Great! Tell me about your research idea.",
            "follow_up": None,
            "input_type": None,
            "quick_replies": [
                {"label": "Continue", "value": "Let's continue"},
            ],
            "field_updates": None,
            "complete": False,
            "payload": None,
        }
        mock_bedrock_class.return_value = mock_service

        response = self.client.post(
            "/api/assistant/chat/",
            {
                "role": "researcher",
                "message": "I want to create a proposal",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("session_id", response.data)
        self.assertIn("message", response.data)

        # Verify session was created
        session = AssistantSession.objects.get(id=response.data["session_id"])
        self.assertEqual(session.user, self.user)
        self.assertEqual(session.role, "researcher")

    @patch("assistant.views.chat_view.BedrockChatService")
    def test_chat_continues_existing_session(self, mock_bedrock_class):
        """Test that an existing session can be continued."""
        # Create a session first
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
        )

        # Mock the Bedrock service
        mock_service = MagicMock()
        mock_service.process_message.return_value = {
            "message": "That sounds interesting!",
            "follow_up": None,
            "input_type": None,
            "quick_replies": [],
            "field_updates": {"title": {"status": "draft", "value": "Test Title"}},
            "complete": False,
            "payload": None,
        }
        mock_bedrock_class.return_value = mock_service

        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(session.id),
                "message": "I want to research AI safety",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["session_id"]), str(session.id))

    def test_chat_rejects_invalid_session_id(self):
        """Test that an invalid session_id is rejected."""
        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(uuid4()),  # Non-existent session
                "message": "Hello",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_chat_rejects_other_users_session(self):
        """Test that users cannot access other users' sessions."""
        from user.models import User

        other_user = User.objects.create_user(
            username="otheruser",
            email="other@test.com",
            password="testpassword123",
        )
        session = AssistantSession.objects.create(
            user=other_user,
            role="researcher",
        )

        response = self.client.post(
            "/api/assistant/chat/",
            {
                "session_id": str(session.id),
                "message": "Hello",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_chat_accepts_valid_roles(self):
        """Test that valid roles are accepted."""
        for role in ["researcher", "funder"]:
            with patch("assistant.views.chat_view.BedrockChatService") as mock_bedrock:
                mock_service = MagicMock()
                mock_service.get_initial_message.return_value = {
                    "message": "Hello!",
                    "follow_up": None,
                    "input_type": None,
                    "quick_replies": [],
                    "field_updates": None,
                    "complete": False,
                    "payload": None,
                }
                mock_service.process_message.return_value = {
                    "message": "Response",
                    "follow_up": None,
                    "input_type": None,
                    "quick_replies": [],
                    "field_updates": None,
                    "complete": False,
                    "payload": None,
                }
                mock_bedrock.return_value = mock_service

                response = self.client.post(
                    "/api/assistant/chat/",
                    {"role": role, "message": "Hello"},
                    format="json",
                )
                self.assertIn(
                    response.status_code,
                    [status.HTTP_200_OK, status.HTTP_201_CREATED],
                    f"Role {role} should be valid",
                )

    def test_chat_rejects_invalid_role(self):
        """Test that invalid roles are rejected."""
        response = self.client.post(
            "/api/assistant/chat/",
            {"role": "invalid_role", "message": "Hello"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SubmitViewTestCase(TestCase):
    """Tests for the SubmitView API endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        from user.models import User

        self.client = APIClient()
        self.user = User.objects.create_user(
            username="submitter",
            email="submitter@test.com",
            password="testpassword123",
        )
        self.client.force_authenticate(user=self.user)

    def test_submit_requires_authentication(self):
        """Test that unauthenticated requests are rejected."""
        self.client.force_authenticate(user=None)
        response = self.client.post(
            "/api/assistant/submit/",
            {"session_id": str(uuid4())},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_submit_requires_session_id(self):
        """Test that session_id is required."""
        response = self.client.post(
            "/api/assistant/submit/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_rejects_invalid_session(self):
        """Test that invalid session_id is rejected."""
        response = self.client.post(
            "/api/assistant/submit/",
            {"session_id": str(uuid4())},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_submit_rejects_incomplete_session(self):
        """Test that incomplete sessions cannot be submitted."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
            is_complete=False,
        )

        response = self.client.post(
            "/api/assistant/submit/",
            {"session_id": str(session.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not complete", response.data["error"])

    def test_submit_rejects_session_without_payload(self):
        """Test that sessions without payload are rejected."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
            is_complete=True,
            payload=None,
        )

        response = self.client.post(
            "/api/assistant/submit/",
            {"session_id": str(session.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No payload", response.data["error"])
