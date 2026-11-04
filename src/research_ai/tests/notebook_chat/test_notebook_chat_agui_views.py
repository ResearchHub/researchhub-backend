from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from rest_framework.test import APITestCase

from note.tests.helpers import create_note
from research_ai.models import AgentExecution
from research_ai.services.notebook_chat import NotebookChatService
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument

MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}
FRAME = 'data: {"type":"RUN_STARTED"}\n\n'


class FakeRelay:
    """Records how the view built the relay; streams one fixed frame."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.execution_id = "unset"
        FakeRelay.instances.append(self)

    async def stream(self, execution_id=None):
        self.execution_id = execution_id
        yield FRAME


async def _collect(response):
    return [chunk async for chunk in response.streaming_content]


def _run_input(*messages, **forwarded):
    return {
        "threadId": "thread",
        "runId": "run-1",
        "state": {},
        "messages": list(messages),
        "tools": [],
        "context": [],
        "forwardedProps": forwarded,
    }


def _user_message(message_id="client-1", content="Summarize the note"):
    return {"id": message_id, "role": "user", "content": content}


@override_settings(**MODEL_SETTINGS)
@patch("research_ai.views.notebook_chat_agui_views.ChatRelay", FakeRelay)
class NotebookChatAguiViewTests(APITestCase):
    def setUp(self):
        FakeRelay.instances = []
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
        self.note, _content = create_note(self.owner, organization=None)
        Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document.id,
            user=self.owner,
        )
        self.conversation = NotebookChatService().create_conversation(
            self.note, self.owner
        )
        self.url = (
            f"/api/research_ai/notebook/notes/{self.note.id}"
            f"/chats/{self.conversation.id}/agui/"
        )

    def _post(self, body, url=None):
        with patch("research_ai.tasks.run_notebook_chat_turn_task.delay") as delay:
            response = self.client.post(
                url or self.url,
                body,
                format="json",
                HTTP_ACCEPT="text/event-stream",
            )
        return response, delay

    def test_a_new_user_message_starts_a_turn_and_streams_it(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post(_run_input(_user_message()))
        frames = async_to_sync(_collect)(response)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(frames, [FRAME.encode()])
        execution = AgentExecution.objects.get(conversation=self.conversation)
        self.assertEqual(execution.trigger_message.content, "Summarize the note")
        (relay,) = FakeRelay.instances
        self.assertEqual(relay.execution_id, execution.id)
        self.assertEqual(relay.kwargs["thread_id"], "thread")
        self.assertEqual(relay.kwargs["run_id"], "run-1")
        self.assertEqual(relay.kwargs["conversation_id"], self.conversation.id)

    def test_forwarded_props_carry_the_model_controls(self):
        # Arrange: model controls are a privileged-tier feature.
        self.owner.moderator = True
        self.owner.save(update_fields=["moderator"])
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post(
            _run_input(_user_message(), effort="high", thinking="adaptive", ignored=1)
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        execution = AgentExecution.objects.get(conversation=self.conversation)
        self.assertEqual(execution.configuration["effort"], "high")
        self.assertEqual(execution.configuration["thinking"], "adaptive")

    def test_a_persisted_trailing_message_does_not_start_a_turn(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post(_run_input(_user_message("msg-41")))
        async_to_sync(_collect)(response)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AgentExecution.objects.exists())
        self.assertIsNone(FakeRelay.instances[0].execution_id)

    def test_connect_never_starts_a_turn(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post(
            _run_input(_user_message()), url=f"{self.url}connect/"
        )
        async_to_sync(_collect)(response)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AgentExecution.objects.exists())

    def test_a_busy_chat_is_a_conflict_before_streaming(self):
        # Arrange
        self.client.force_authenticate(self.owner)
        self._post(_run_input(_user_message()))

        # Act
        response, _delay = self._post(_run_input(_user_message("client-2", "More")))

        # Assert
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(len(FakeRelay.instances), 1)

    def test_an_invalid_message_is_rejected(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post(_run_input(_user_message(content="   ")))

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AgentExecution.objects.exists())

    def test_invalid_run_input_is_rejected(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        response, _delay = self._post({"messages": "nope"})

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Invalid AG-UI run input.")

    def test_another_users_chat_is_not_found(self):
        # Arrange
        self.client.force_authenticate(self.other)

        # Act
        response, _delay = self._post(_run_input(_user_message()))

        # Assert
        self.assertEqual(response.status_code, 404)
        self.assertFalse(FakeRelay.instances)

    def test_requires_authentication(self):
        # Act
        response, _delay = self._post(_run_input(_user_message()))

        # Assert
        self.assertEqual(response.status_code, 401)
