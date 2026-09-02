from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
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
        self.chats_url = f"/api/research_ai/notebook/notes/{self.note.id}/chats/"

    def _chat_url(self, conversation_id):
        return f"{self.chats_url}{conversation_id}/"

    def _create_chat(self, **payload):
        return self.client.post(self.chats_url, payload, format="json")

    def _create_chat_id(self):
        response = self._create_chat()
        self.assertEqual(response.status_code, 201)
        return response.data["conversation_id"]

    def _post_message(self, conversation_id, text="Summarize the note", **extra):
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay") as delay:
            response = self.client.post(
                f"{self._chat_url(conversation_id)}messages/",
                {"message": text, **extra},
                format="json",
            )
        return response, delay

    def _cancel(self, conversation_id):
        return self.client.post(f"{self._chat_url(conversation_id)}cancel/")

    # -- creating chats ---------------------------------------------------

    def test_create_chat_returns_an_empty_representation(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self._create_chat()

        # Assert
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(response.data["conversation_id"])
        self.assertEqual(response.data["title"], "")
        self.assertEqual(response.data["messages"], [])
        self.assertEqual(response.data["executions"], [])

    def test_create_chat_accepts_a_title(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self._create_chat(title="Methods discussion")

        # Assert
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["title"], "Methods discussion")

    def test_a_user_can_keep_several_chats_on_one_note(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        first = self._create_chat_id()
        second = self._create_chat_id()

        # Assert
        self.assertNotEqual(first, second)
        listing = self.client.get(self.chats_url)
        self.assertEqual(len(listing.data["chats"]), 2)

    def test_create_chat_requires_note_access(self):
        # Arrange
        self.client.force_authenticate(self.outsider)

        # Act
        response = self._create_chat()

        # Assert
        self.assertEqual(response.status_code, 404)

    # -- sending messages -------------------------------------------------

    def test_post_message_starts_a_turn(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(chat_id)

        # Assert
        self.assertEqual(response.status_code, 202)
        execution = AgentExecution.objects.get(id=response.data["execution_id"])
        self.assertEqual(execution.status, AgentExecution.Status.PENDING)
        self.assertEqual(response.data["conversation_id"], chat_id)
        self.assertEqual(execution.trigger_message.content, "Summarize the note")

    @override_settings(
        ANTHROPIC_AWS_WORKSPACE_ID="ws-test", AWS_REGION_NAME="us-east-1"
    )
    def test_post_message_records_a_selected_model(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(
            chat_id, model="claude_platform:claude-sonnet-5"
        )

        # Assert
        self.assertEqual(response.status_code, 202)
        execution = AgentExecution.objects.get(id=response.data["execution_id"])
        self.assertEqual(execution.model, "claude_platform:claude-sonnet-5")

    def test_post_message_records_effort_and_thinking(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(
            chat_id,
            effort="high",
            thinking="disabled",
        )

        # Assert
        self.assertEqual(response.status_code, 202)
        execution = AgentExecution.objects.get(id=response.data["execution_id"])
        self.assertEqual(execution.configuration["effort"], "high")
        self.assertEqual(execution.configuration["thinking"], "disabled")

    def test_post_message_with_unknown_model_is_rejected(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(chat_id, model="openrouter:acme/nope")

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("model", response.data)
        self.assertFalse(AgentExecution.objects.exists())

    @override_settings(
        ANTHROPIC_AWS_WORKSPACE_ID="ws-test", AWS_REGION_NAME="us-east-1"
    )
    def test_post_message_cannot_switch_the_conversation_model(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        first_response, _delay = self._post_message(
            chat_id, model="claude_platform:claude-sonnet-5"
        )
        first = AgentExecution.objects.get(id=first_response.data["execution_id"])
        first.status = AgentExecution.Status.SUCCEEDED
        first.save(update_fields=["status"])

        # Act
        response, _delay = self._post_message(
            chat_id,
            text="Use another model",
            model="claude_platform:claude-opus-5",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("model cannot be changed", response.data["detail"])
        self.assertEqual(AgentExecution.objects.count(), 1)

    def test_post_message_as_viewer_is_allowed(self):
        # Arrange: viewers can chat; the edit tool refuses writes for them.
        self.client.force_authenticate(self.viewer)
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(chat_id)

        # Assert
        self.assertEqual(response.status_code, 202)

    def test_post_message_to_another_users_chat_is_not_found(self):
        # Arrange: the viewer knows the owner's chat id but must not reach it.
        self.client.force_authenticate(self.owner)
        owners_chat = self._create_chat_id()
        self.client.force_authenticate(self.viewer)

        # Act
        response, _delay = self._post_message(owners_chat)

        # Assert
        self.assertEqual(response.status_code, 404)
        self.assertFalse(AgentExecution.objects.exists())

    def test_post_message_to_unknown_chat_is_not_found(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post_message(999999)

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_deleted_note_chat_is_hidden(self):
        # Arrange: a chat exists, then the note is soft-deleted.
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        self._post_message(chat_id)
        self.note.unified_document.is_removed = True
        self.note.unified_document.save(update_fields=["is_removed"])

        # Act
        list_response = self.client.get(self.chats_url)
        get_response = self.client.get(self._chat_url(chat_id))
        post_response, _delay = self._post_message(chat_id)

        # Assert: same deletion boundary as NoteViewSet -- the note, its chat
        # history, and new turns are all gone (404, not the busy 409).
        self.assertEqual(list_response.status_code, 404)
        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(post_response.status_code, 404)

    def test_regular_user_with_note_access_can_use_default_tier(self):
        # Arrange: full note access and the default Research AI tier.
        self.client.force_authenticate(self.regular_user)

        # Act
        create_response = self._create_chat()
        list_response = self.client.get(self.chats_url)

        # Assert
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(list_response.status_code, 200)

    def test_post_message_requires_authentication(self):
        # Act
        response = self.client.post(
            f"{self._chat_url(1)}messages/", {"message": "hi"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_post_empty_message_is_rejected(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response, _delay = self._post_message(chat_id, "")

        # Assert
        self.assertEqual(response.status_code, 400)

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

    def test_busy_chat_blocks_the_users_other_chats(self):
        # Arrange: a turn is running in the first chat.
        self.client.force_authenticate(self.owner)
        busy_chat = self._create_chat_id()
        self._post_message(busy_chat)
        other_chat = self._create_chat_id()

        # Act
        response, _delay = self._post_message(other_chat, "Separate thread")

        # Assert: budget admission is per user so parallel chats cannot race
        # against the same usage snapshot.
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "usage_work_in_progress")

    # -- cancelling -------------------------------------------------------

    def test_cancel_stops_the_running_turn_and_frees_the_chat(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        posted, _delay = self._post_message(chat_id)

        # Act
        response = self._cancel(chat_id)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["cancelled"])
        self.assertEqual(response.data["execution_id"], posted.data["execution_id"])
        execution = AgentExecution.objects.get(id=posted.data["execution_id"])
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        # The whole point: the user can send the next message immediately.
        again, _delay = self._post_message(chat_id, "Try this instead")
        self.assertEqual(again.status_code, 202)

    def test_cancel_with_nothing_running_succeeds_and_reports_nothing(self):
        # Arrange: the client cannot know which side of the race it is on when
        # the user clicks stop, so this is a success, not an error.
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response = self._cancel(chat_id)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["cancelled"])
        self.assertIsNone(response.data["execution_id"])

    def test_cancel_of_another_users_chat_is_not_found(self):
        # Arrange: the owner's turn is running; the viewer aims stop at it.
        self.client.force_authenticate(self.owner)
        owners_chat = self._create_chat_id()
        posted, _delay = self._post_message(owners_chat)
        self.client.force_authenticate(self.viewer)

        # Act
        response = self._cancel(owners_chat)

        # Assert: not reachable, and the owner's turn is untouched.
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            AgentExecution.objects.get(id=posted.data["execution_id"]).status,
            AgentExecution.Status.PENDING,
        )

    def test_cancel_idle_chat_does_not_touch_the_users_running_chat(self):
        # Arrange: a turn is running in one chat and single-flight admission
        # refuses a second turn in another chat.
        self.client.force_authenticate(self.owner)
        first_chat = self._create_chat_id()
        first_posted, _delay = self._post_message(first_chat)
        second_chat = self._create_chat_id()
        second_posted, _delay = self._post_message(second_chat)
        self.assertEqual(second_posted.status_code, 409)

        # Act
        response = self._cancel(second_chat)

        # Assert
        self.assertFalse(response.data["cancelled"])
        self.assertIsNone(response.data["execution_id"])
        self.assertEqual(
            AgentExecution.objects.get(id=first_posted.data["execution_id"]).status,
            AgentExecution.Status.PENDING,
        )

    # -- reading chats ----------------------------------------------------

    def test_list_chats_starts_empty(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.get(self.chats_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["chats"], [])

    def test_list_chats_shows_titles_previews_and_activity(self):
        # Arrange: one busy chat named from its first message, one idle chat.
        self.client.force_authenticate(self.owner)
        idle_chat = self._create_chat_id()
        busy_chat = self._create_chat_id()
        self._post_message(busy_chat, "Compare the cited methods")

        # Act
        response = self.client.get(self.chats_url)

        # Assert: newest activity first.
        busy, idle = response.data["chats"]
        self.assertEqual(busy["id"], busy_chat)
        self.assertEqual(busy["title"], "Compare the cited methods")
        self.assertEqual(busy["last_message_preview"], "Compare the cited methods")
        self.assertTrue(busy["has_active_turn"])
        self.assertEqual(idle["id"], idle_chat)
        self.assertFalse(idle["has_active_turn"])

    def test_get_chat_returns_its_representation(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()
        self._post_message(chat_id, "What is this note about?")

        # Act
        response = self.client.get(self._chat_url(chat_id))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["conversation_id"], chat_id)
        self.assertEqual(response.data["title"], "What is this note about?")
        self.assertEqual(len(response.data["messages"]), 1)
        self.assertEqual(
            response.data["messages"][0]["content"], "What is this note about?"
        )
        self.assertIsNotNone(response.data["messages"][0]["created_date"])
        self.assertEqual(len(response.data["executions"]), 1)
        self.assertEqual(
            response.data["executions"][0]["status"],
            AgentExecution.Status.PENDING,
        )

    def test_get_unknown_chat_is_not_found(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response = self.client.get(self._chat_url(999999))

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_chats_are_scoped_per_user(self):
        # Arrange: the owner has a chat; the viewer neither lists nor reads it.
        self.client.force_authenticate(self.owner)
        owners_chat = self._create_chat_id()
        self.client.force_authenticate(self.viewer)

        # Act
        listing = self.client.get(self.chats_url)
        detail = self.client.get(self._chat_url(owners_chat))

        # Assert
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["chats"], [])
        self.assertEqual(detail.status_code, 404)

    def test_list_chats_requires_note_access(self):
        # Arrange
        self.client.force_authenticate(self.outsider)

        # Act
        response = self.client.get(self.chats_url)

        # Assert
        self.assertEqual(response.status_code, 404)

    # -- renaming ---------------------------------------------------------

    def test_rename_chat(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response = self.client.patch(
            self._chat_url(chat_id), {"title": "Grant ideas"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Grant ideas")
        detail = self.client.get(self._chat_url(chat_id))
        self.assertEqual(detail.data["title"], "Grant ideas")

    def test_rename_chat_rejects_a_blank_title(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        chat_id = self._create_chat_id()

        # Act
        response = self.client.patch(
            self._chat_url(chat_id), {"title": ""}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_rename_of_another_users_chat_is_not_found(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        owners_chat = self._create_chat_id()
        self.client.force_authenticate(self.viewer)

        # Act
        response = self.client.patch(
            self._chat_url(owners_chat), {"title": "Mine now"}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 404)
