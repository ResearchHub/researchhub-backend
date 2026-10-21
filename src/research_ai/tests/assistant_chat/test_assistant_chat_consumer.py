import json

from asgiref.testing import ApplicationCommunicator
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase

import research_ai.routing
from research_ai.consumers import (
    CLOSE_FORBIDDEN,
    CLOSE_NOT_FOUND,
    CLOSE_UNAUTHENTICATED,
)
from research_ai.services.assistant_chat import AssistantChatService
from research_ai.services.notebook_chat.events import EVENT_TYPE, conversation_group

application = URLRouter(research_ai.routing.websocket_urlpatterns)


class AssistantChatConsumerTests(TransactionTestCase):
    """Admission mirrors the REST contract; events are forwarded verbatim."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other_user = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )
        service = AssistantChatService()
        self.conversation = service.create_conversation(self.user)
        self.other_conversation = service.create_conversation(self.other_user)

    async def _connect(self, user, *, conversation_id=None):
        conversation_id = (
            self.conversation.id if conversation_id is None else conversation_id
        )
        communicator = ApplicationCommunicator(
            application,
            {
                "type": "websocket",
                "path": f"/ws/assistant/chats/{conversation_id}/",
                "user": user,
            },
        )
        await communicator.send_input({"type": "websocket.connect"})
        return communicator, await communicator.receive_output()

    async def test_anonymous_connection_is_rejected(self):
        # Act
        _communicator, response = await self._connect(AnonymousUser())

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_UNAUTHENTICATED)

    async def test_regular_user_can_connect_to_own_conversation(self):
        # Arrange: the user has no editor or moderator role.
        user = self.other_user

        # Act
        communicator, response = await self._connect(
            user, conversation_id=self.other_conversation.id
        )

        # Assert
        self.assertEqual(response["type"], "websocket.accept")
        await communicator.send_input({"type": "websocket.disconnect", "code": 1000})
        await communicator.wait()

    async def test_suspended_user_is_rejected(self):
        # Arrange
        self.user.is_suspended = True
        await self.user.asave(update_fields=["is_suspended"])

        # Act
        _communicator, response = await self._connect(self.user)

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_FORBIDDEN)

    async def test_someone_elses_conversation_reads_as_not_found(self):
        # Arrange: a moderator who does not own the chat.
        self.other_user.moderator = True
        await self.other_user.asave(update_fields=["moderator"])

        # Act
        _communicator, response = await self._connect(self.other_user)

        # Assert
        self.assertEqual(response["type"], "websocket.close")
        self.assertEqual(response["code"], CLOSE_NOT_FOUND)

    async def test_owner_connects_and_receives_published_events(self):
        # Arrange
        communicator, response = await self._connect(self.user)
        self.assertEqual(response["type"], "websocket.accept")
        self.assertEqual(response["subprotocol"], "Token")
        event = {
            "conversation_id": self.conversation.id,
            "execution_id": 5,
            "kind": "turn_progress",
        }

        # Act
        await get_channel_layer().group_send(
            conversation_group(self.conversation.id),
            {"type": EVENT_TYPE, "data": event},
        )

        # Assert
        output = await communicator.receive_output()
        self.assertEqual(output["type"], "websocket.send")
        self.assertEqual(json.loads(output["text"]), event)
        await communicator.send_input({"type": "websocket.disconnect", "code": 1000})
        await communicator.wait()
