from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from note.tests.helpers import create_note
from research_ai.models import AgentExecution
from researchhub_access_group.constants import ADMIN, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument


class NotebookChatViewTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.viewer = user_model.objects.create_user(
            username="viewer@researchhub_test.com",
            password="password",
            email="viewer@researchhub_test.com",
        )
        self.outsider = user_model.objects.create_user(
            username="outsider@researchhub_test.com",
            password="password",
            email="outsider@researchhub_test.com",
        )
        # A collaborator on the note who is neither a hub editor nor a
        # moderator, to exercise the rollout gate.
        self.regular_user = user_model.objects.create_user(
            username="regular@researchhub_test.com",
            password="password",
            email="regular@researchhub_test.com",
        )
        # The feature is gated to hub editors and moderators for now; note
        # access is still checked separately, so the outsider is a moderator
        # too (they must clear the gate to exercise the 404 path).
        for user in (self.owner, self.viewer, self.outsider):
            user.moderator = True
            user.save(update_fields=["moderator"])
        self.note, self.content = create_note(self.owner, organization=None)
        unified_doc_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=unified_doc_ct,
            object_id=self.note.unified_document.id,
            user=self.owner,
        )
        Permission.objects.create(
            access_type=VIEWER,
            content_type=unified_doc_ct,
            object_id=self.note.unified_document.id,
            user=self.viewer,
        )
        Permission.objects.create(
            access_type=ADMIN,
            content_type=unified_doc_ct,
            object_id=self.note.unified_document.id,
            user=self.regular_user,
        )
        self.chat_url = f"/api/research_ai/notebook/notes/{self.note.id}/chat/"
        self.messages_url = f"{self.chat_url}messages/"
        self.cancel_url = f"{self.chat_url}cancel/"

    def _post_message(self, text="Summarize the note"):
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay") as delay:
            response = self.client.post(
                self.messages_url, {"message": text}, format="json"
            )
        return response, delay

    def test_post_message_starts_a_turn(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post_message()

        # Assert
        self.assertEqual(response.status_code, 202)
        execution = AgentExecution.objects.get(id=response.data["execution_id"])
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)
        self.assertEqual(response.data["conversation_id"], execution.conversation_id)
        self.assertEqual(execution.trigger_message.content, "Summarize the note")

    def test_post_message_as_viewer_is_allowed(self):
        # Arrange: viewers can chat; the edit tool refuses writes for them.
        self.client.force_authenticate(self.viewer)

        # Act
        response, _delay = self._post_message()

        # Assert
        self.assertEqual(response.status_code, 202)

    def test_post_message_requires_note_access(self):
        # Arrange
        self.client.force_authenticate(self.outsider)

        # Act
        response, _delay = self._post_message()

        # Assert
        self.assertEqual(response.status_code, 404)
        self.assertFalse(AgentExecution.objects.exists())

    def test_deleted_note_chat_is_hidden(self):
        # Arrange: a chat exists, then the note is soft-deleted.
        self.client.force_authenticate(self.owner)
        self._post_message()
        self.note.unified_document.is_removed = True
        self.note.unified_document.save(update_fields=["is_removed"])

        # Act
        get_response = self.client.get(self.chat_url)
        post_response, _delay = self._post_message()

        # Assert: same deletion boundary as NoteViewSet -- the note, its chat
        # history, and new turns are all gone (404, not the busy 409).
        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(post_response.status_code, 404)

    def test_gate_blocks_regular_users_even_with_note_access(self):
        # Arrange: full note access, but neither hub editor nor moderator.
        self.client.force_authenticate(self.regular_user)

        # Act
        post_response, _delay = self._post_message()
        get_response = self.client.get(self.chat_url)

        # Assert
        self.assertEqual(post_response.status_code, 403)
        self.assertEqual(get_response.status_code, 403)
        self.assertFalse(AgentExecution.objects.exists())

    def test_post_message_requires_authentication(self):
        # Act
        response = self.client.post(self.messages_url, {"message": "hi"}, format="json")

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_post_empty_message_is_rejected(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post_message("")

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_post_while_turn_is_running_returns_conflict(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        first, _delay = self._post_message()
        self.assertEqual(first.status_code, 202)

        # Act
        second, _delay = self._post_message("another")

        # Assert
        self.assertEqual(second.status_code, 409)

    def test_cancel_stops_the_running_turn_and_frees_the_conversation(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        posted, _delay = self._post_message()

        # Act
        response = self.client.post(self.cancel_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["cancelled"])
        self.assertEqual(response.data["execution_id"], posted.data["execution_id"])
        execution = AgentExecution.objects.get(id=posted.data["execution_id"])
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        # The whole point: the user can send the next message immediately.
        again, _delay = self._post_message("Try this instead")
        self.assertEqual(again.status_code, 202)

    def test_cancel_with_nothing_running_succeeds_and_reports_nothing(self):
        # Arrange: the client cannot know which side of the race it is on when
        # the user clicks stop, so this is a success, not an error.
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.post(self.cancel_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["cancelled"])
        self.assertIsNone(response.data["execution_id"])

    def test_cancel_requires_note_access(self):
        # Arrange
        self.client.force_authenticate(self.outsider)

        # Act
        response = self.client.post(self.cancel_url)

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_cancel_is_scoped_to_the_requesting_users_conversation(self):
        # Arrange: the owner has a turn running; the viewer has their own
        # conversation on the same note.
        self.client.force_authenticate(self.owner)
        posted, _delay = self._post_message()
        self.client.force_authenticate(self.viewer)

        # Act
        response = self.client.post(self.cancel_url)

        # Assert: the viewer cannot stop someone else's turn.
        self.assertFalse(response.data["cancelled"])
        execution = AgentExecution.objects.get(id=posted.data["execution_id"])
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)

    def test_get_chat_without_conversation_returns_empty(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.get(self.chat_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["conversation_id"])
        self.assertEqual(response.data["messages"], [])
        self.assertEqual(response.data["executions"], [])

    def test_get_chat_returns_the_users_conversation(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        posted, _delay = self._post_message("What is this note about?")

        # Act
        response = self.client.get(self.chat_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["conversation_id"], posted.data["conversation_id"]
        )
        self.assertEqual(len(response.data["messages"]), 1)
        self.assertEqual(
            response.data["messages"][0]["content"], "What is this note about?"
        )
        self.assertEqual(len(response.data["executions"]), 1)
        self.assertEqual(
            response.data["executions"][0]["status"],
            AgentExecution.Status.PENDING,
        )

    def test_get_chat_is_scoped_per_user(self):
        # Arrange: the owner has a conversation; the viewer sees their own
        # (empty) chat, not the owner's.
        self.client.force_authenticate(self.owner)
        self._post_message()
        self.client.force_authenticate(self.viewer)

        # Act
        response = self.client.get(self.chat_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["conversation_id"])

    def test_get_chat_requires_note_access(self):
        # Arrange
        self.client.force_authenticate(self.outsider)

        # Act
        response = self.client.get(self.chat_url)

        # Assert
        self.assertEqual(response.status_code, 404)
