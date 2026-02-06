from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from assistant.models import AssistantSession
from assistant.services.bedrock_chat_service import BedrockChatService


class BedrockChatServiceTestCase(TestCase):
    """Tests for the BedrockChatService."""

    def setUp(self):
        """Set up test fixtures."""
        from user.models import User

        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@test.com",
            password="testpassword123",
        )
        self.session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
        )

    @override_settings(ASSISTANT_ENABLED=False)
    def test_service_disabled_returns_fallback(self):
        """Test that disabled service returns fallback response."""
        service = BedrockChatService()
        result = service.process_message(self.session, "Hello")

        self.assertIn("unavailable", result["message"])
        self.assertFalse(result["complete"])

    def test_get_initial_message_researcher(self):
        """Test initial message for researcher role."""
        service = BedrockChatService()
        result = service.get_initial_message("researcher")

        self.assertIn("proposal", result["message"].lower())
        self.assertIsNotNone(result["quick_replies"])
        self.assertGreater(len(result["quick_replies"]), 0)
        self.assertFalse(result["complete"])

    def test_get_initial_message_funder(self):
        """Test initial message for funder role."""
        service = BedrockChatService()
        result = service.get_initial_message("funder")

        self.assertIn("funding", result["message"].lower())
        self.assertIsNotNone(result["quick_replies"])
        self.assertGreater(len(result["quick_replies"]), 0)
        self.assertFalse(result["complete"])

    def test_parse_structured_output_valid(self):
        """Test parsing valid structured output."""
        service = BedrockChatService()
        response = """
        Here's my response!

        <structured>
        {
            "input_type": "topic_select",
            "quick_replies": [
                {"label": "Yes", "value": "Yes, continue"},
                {"label": "No", "value": null}
            ],
            "field_updates": {
                "title": {"status": "draft", "value": "Test Title"}
            },
            "follow_up": null
        }
        </structured>
        """

        result = service._parse_structured_output(response)

        self.assertEqual(result["input_type"], "topic_select")
        self.assertEqual(len(result["quick_replies"]), 2)
        self.assertIn("title", result["field_updates"])
        self.assertEqual(result["field_updates"]["title"]["status"], "draft")

    def test_parse_structured_output_missing(self):
        """Test parsing response without structured output."""
        service = BedrockChatService()
        response = "Just a plain response without any structured data."

        result = service._parse_structured_output(response)

        self.assertIsNone(result["input_type"])
        self.assertIsNone(result["quick_replies"])
        self.assertIsNone(result["field_updates"])

    def test_parse_structured_output_invalid_json(self):
        """Test parsing response with invalid JSON in structured output."""
        service = BedrockChatService()
        response = """
        Response text.

        <structured>
        { invalid json here }
        </structured>
        """

        result = service._parse_structured_output(response)

        self.assertIsNone(result["input_type"])
        self.assertIsNone(result["quick_replies"])

    def test_extract_clean_message(self):
        """Test extracting clean message without structured tags."""
        service = BedrockChatService()
        response = """Here's my helpful response!

<structured>
{"input_type": null, "quick_replies": null, "field_updates": null}
</structured>"""

        clean = service._extract_clean_message(response)

        self.assertNotIn("<structured>", clean)
        self.assertNotIn("</structured>", clean)
        self.assertIn("helpful response", clean)

    def test_build_user_message_plain(self):
        """Test building plain user message."""
        service = BedrockChatService()
        result = service._build_user_message("Hello", None)

        self.assertEqual(result, "Hello")

    def test_build_user_message_with_author_ids(self):
        """Test building user message with author selection."""
        service = BedrockChatService()
        result = service._build_user_message(
            "I selected some authors", {"field": "author_ids", "value": [1, 2, 3]}
        )

        self.assertIn("Selected authors", result)
        self.assertIn("[1, 2, 3]", result)

    def test_build_user_message_with_topic_ids(self):
        """Test building user message with topic selection."""
        service = BedrockChatService()
        result = service._build_user_message(
            "Selected topics", {"field": "topic_ids", "value": [5, 10]}
        )

        self.assertIn("Selected topics", result)
        self.assertIn("[5, 10]", result)

    def test_build_messages_format(self):
        """Test building messages for Bedrock API."""
        service = BedrockChatService()
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        messages = service._build_messages(history)

        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], [{"text": "Hello"}])
        self.assertEqual(messages[1]["role"], "assistant")

    def test_build_payload_researcher(self):
        """Test building payload for researcher."""
        service = BedrockChatService()
        self.session.field_state = {
            "title": {"status": "complete", "value": "Test Research Title"},
            "description": {"status": "complete", "value": "Test description here"},
            "topic_ids": {"status": "complete", "value": [1, 2]},
            "funding_amount_rsc": {"status": "complete", "value": 1000},
        }

        payload = service._build_payload(self.session)

        self.assertEqual(payload["title"], "Test Research Title")
        self.assertEqual(payload["renderable_text"], "Test description here")
        self.assertEqual(payload["document_type"], "PREREGISTRATION")
        self.assertEqual(payload["hubs"], [1, 2])
        self.assertEqual(payload["fundraise_goal_amount"], 1000)

    def test_build_payload_funder(self):
        """Test building payload for funder."""
        service = BedrockChatService()
        funder_session = AssistantSession.objects.create(
            user=self.user,
            role="funder",
            field_state={
                "title": {"status": "complete", "value": "Funding Opportunity"},
                "description": {"status": "complete", "value": "Fund AI research"},
                "amount": {"status": "complete", "value": 50000},
                "topic_ids": {"status": "complete", "value": [3, 4]},
            },
        )

        payload = service._build_payload(funder_session)

        self.assertEqual(payload["title"], "Funding Opportunity")
        self.assertEqual(payload["description"], "Fund AI research")
        self.assertEqual(payload["amount"], 50000)
        self.assertEqual(payload["hubs"], [3, 4])

    @patch("assistant.services.bedrock_chat_service.create_client")
    @override_settings(ASSISTANT_ENABLED=True)
    def test_call_bedrock_success(self, mock_create_client):
        """Test successful Bedrock API call."""
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "This is the response text."}]}}
        }
        mock_create_client.return_value = mock_client

        service = BedrockChatService()
        result = service._call_bedrock(
            "System prompt", [{"role": "user", "content": [{"text": "Hello"}]}]
        )

        self.assertEqual(result, "This is the response text.")
        mock_client.converse.assert_called_once()

    @patch("assistant.services.bedrock_chat_service.create_client")
    @override_settings(ASSISTANT_ENABLED=True)
    def test_call_bedrock_failure(self, mock_create_client):
        """Test Bedrock API call failure."""
        mock_client = MagicMock()
        mock_client.converse.side_effect = Exception("API Error")
        mock_create_client.return_value = mock_client

        service = BedrockChatService()
        result = service._call_bedrock(
            "System prompt", [{"role": "user", "content": [{"text": "Hello"}]}]
        )

        self.assertIsNone(result)


class AssistantSessionModelTestCase(TestCase):
    """Tests for the AssistantSession model."""

    def setUp(self):
        """Set up test fixtures."""
        from user.models import User

        self.user = User.objects.create_user(
            username="sessiontestuser",
            email="testuser@test.com",
            password="testpassword123",
        )

    def test_add_message(self):
        """Test adding messages to conversation history."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
        )

        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there!")

        self.assertEqual(len(session.conversation_history), 2)
        self.assertEqual(session.conversation_history[0]["role"], "user")
        self.assertEqual(session.conversation_history[0]["content"], "Hello")

    def test_update_field(self):
        """Test updating field state."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
        )

        session.update_field("title", "draft", "My Research")
        session.update_field("title", "complete", "My Final Title")

        self.assertEqual(session.field_state["title"]["status"], "complete")
        self.assertEqual(session.field_state["title"]["value"], "My Final Title")

    def test_get_field_value(self):
        """Test getting field value."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
            field_state={"title": {"status": "complete", "value": "Test Title"}},
        )

        self.assertEqual(session.get_field_value("title"), "Test Title")
        self.assertIsNone(session.get_field_value("nonexistent"))

    def test_get_complete_fields(self):
        """Test getting only complete fields."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
            field_state={
                "title": {"status": "complete", "value": "Test Title"},
                "description": {"status": "draft", "value": "Draft desc"},
                "topic_ids": {"status": "complete", "value": [1, 2]},
            },
        )

        complete = session.get_complete_fields()

        self.assertIn("title", complete)
        self.assertNotIn("description", complete)
        self.assertIn("topic_ids", complete)

    def test_get_required_fields_researcher(self):
        """Test required fields for researcher."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
        )

        required = session.get_required_fields()

        self.assertIn("title", required)
        self.assertIn("description", required)
        self.assertIn("topic_ids", required)

    def test_get_required_fields_funder(self):
        """Test required fields for funder."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="funder",
        )

        required = session.get_required_fields()

        self.assertIn("title", required)
        self.assertIn("description", required)
        self.assertIn("amount", required)
        self.assertIn("topic_ids", required)

    def test_check_completion_incomplete(self):
        """Test completion check when incomplete."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
            field_state={
                "title": {"status": "complete", "value": "Test"},
            },
        )

        self.assertFalse(session.check_completion())

    def test_check_completion_complete(self):
        """Test completion check when complete."""
        session = AssistantSession.objects.create(
            user=self.user,
            role="researcher",
            field_state={
                "title": {"status": "complete", "value": "Test Title"},
                "description": {"status": "complete", "value": "Test description"},
                "topic_ids": {"status": "complete", "value": [1, 2]},
            },
        )

        self.assertTrue(session.check_completion())
