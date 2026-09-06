from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from note.tests.helpers import create_note
from research_ai.models import AgentExecution
from research_ai.services.notebook_chat import NotebookChatService

MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}

CHATS_URL = "/api/research_ai/assistant/chats/"


@override_settings(**MODEL_SETTINGS)
class AssistantChatViewTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )
        # Neither editor nor moderator: exercises the rollout gate.
        self.regular_user = user_model.objects.create_user(
            username="regular@researchhub_test.com",
            password="password",
            email="regular@researchhub_test.com",
        )
        for user in (self.owner, self.other):
            user.moderator = True
            user.save(update_fields=["moderator"])

    def _chat_url(self, conversation_id):
        return f"{CHATS_URL}{conversation_id}/"

    def _create_chat_id(self, **payload):
        response = self.client.post(CHATS_URL, payload, format="json")
        self.assertEqual(response.status_code, 201)
        return response.data["conversation_id"]

    def _post_message(self, conversation_id, text="Find papers on CRISPR", **extra):
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay") as delay:
            response = self.client.post(
                f"{self._chat_url(conversation_id)}messages/",
                {"message": text, **extra},
                format="json",
            )
        return response, delay

    # -- creating and listing ---------------------------------------------

    def test_create_chat_returns_an_empty_representation_with_no_notes(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post(CHATS_URL, {"title": "Grants"}, format="json")

        # Assert
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["title"], "Grants")
        self.assertEqual(response.data["messages"], [])
        self.assertEqual(response.data["executions"], [])
        self.assertEqual(response.data["notes"], [])

    def test_gate_blocks_regular_users(self):
        # Arrange
        self.client.force_authenticate(self.regular_user)

        # Act
        response = self.client.post(CHATS_URL, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_requires_authentication(self):
        # Act
        response = self.client.get(CHATS_URL)

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_list_chats_is_scoped_to_the_user(self):
        # Arrange: the owner has one busy chat and one idle chat; another
        # user has a chat of their own.
        self.client.force_authenticate(self.owner)
        idle_chat = self._create_chat_id()
        busy_chat = self._create_chat_id()
        self._post_message(busy_chat, "Compare the cited methods")
        self.client.force_authenticate(self.other)
        self._create_chat_id()

        # Act
        self.client.force_authenticate(self.owner)
        response = self.client.get(CHATS_URL)

        # Assert: newest activity first, nobody else's chats.
        busy, idle = response.data["chats"]
        self.assertEqual(busy["id"], busy_chat)
        self.assertEqual(busy["title"], "Compare the cited methods")
        self.assertTrue(busy["has_active_turn"])
        self.assertEqual(idle["id"], idle_chat)
        self.assertFalse(idle["has_active_turn"])

    def test_assistant_chats_do_not_appear_among_notebook_chats(self):
        # Arrange: an assistant chat and a notebook chat for the same user.
        self.client.force_authenticate(self.owner)
        self._create_chat_id()
        note, _content = create_note(self.owner, organization=None)
        NotebookChatService().create_conversation(note, self.owner)

        # Act
        listing = self.client.get(CHATS_URL)

        # Assert: the notebook chat is not an assistant chat, and the
        # assistant chat is not on the note either.
        self.assertEqual(len(listing.data["chats"]), 1)
        self.assertEqual(
            len(NotebookChatService().list_conversations(note, self.owner)), 1
        )

    # -- messages -----------------------------------------------------------

    def test_post_message_starts_a_note_less_turn(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(chat_id)

        # Assert
        self.assertEqual(response.status_code, 202)
        execution = AgentExecution.objects.get(id=response.data["execution_id"])
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)
        self.assertNotIn("note_id", execution.configuration)
        self.assertIn("create_note", execution.system_prompt)

    def test_post_message_to_another_users_chat_is_not_found(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        self.client.force_authenticate(self.other)

        # Act
        response, _delay = self._post_message(chat_id)

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_post_while_turn_is_running_returns_conflict(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        first, _delay = self._post_message(chat_id)
        self.assertEqual(first.status_code, 202)

        # Act
        second, _delay = self._post_message(chat_id, "another")

        # Assert
        self.assertEqual(second.status_code, 409)

    def test_busy_notebook_chat_blocks_the_assistant_chat(self):
        # Arrange: budget admission is per user, across workflows.
        self.client.force_authenticate(self.owner)
        note, _content = create_note(self.owner, organization=None)
        notebook_chat = NotebookChatService().create_conversation(note, self.owner)
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay"):
            NotebookChatService().submit_message(note, notebook_chat, "Busy")
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(chat_id)

        # Assert
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "usage_work_in_progress")

    # -- detail, cancel, rename ---------------------------------------------

    def test_get_chat_returns_its_representation(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        self._post_message(chat_id, "Hello")

        # Act
        response = self.client.get(self._chat_url(chat_id))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["conversation_id"], chat_id)
        self.assertEqual(response.data["messages"][0]["content"], "Hello")
        self.assertEqual(response.data["notes"], [])

    def test_get_another_users_chat_is_not_found(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        self.client.force_authenticate(self.other)

        # Act
        response = self.client.get(self._chat_url(chat_id))

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_cancel_stops_the_running_turn(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        posted, _delay = self._post_message(chat_id)

        # Act
        response = self.client.post(f"{self._chat_url(chat_id)}cancel/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["cancelled"])
        execution = AgentExecution.objects.get(id=posted.data["execution_id"])
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)

    def test_rename_chat(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response = self.client.patch(
            self._chat_url(chat_id), {"title": "Funding"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Funding")
