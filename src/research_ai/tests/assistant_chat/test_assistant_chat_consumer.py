import json
from unittest.mock import patch

from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
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
        self.user.moderator = True
        self.user.save(update_fields=["moderator"])
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
        communicator = WebsocketCommunicator(
            application, f"/ws/assistant/chats/{conversation_id}/"
        )
        communicator.scope["user"] = user
        connected, detail = await communicator.connect()
        return communicator, connected, detail

    async def test_anonymous_connection_is_rejected(self):
        # Act
        _communicator, connected, code = await self._connect(AnonymousUser())

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_UNAUTHENTICATED)

    async def test_user_outside_the_rollout_gate_is_rejected(self):
        # Act: authenticated, but neither editor nor moderator.
        _communicator, connected, code = await self._connect(
            self.other_user, conversation_id=self.other_conversation.id
        )

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_FORBIDDEN)

    async def test_someone_elses_conversation_reads_as_not_found(self):
        # Arrange: a moderator who does not own the chat.
        self.other_user.moderator = True
        await self.other_user.asave(update_fields=["moderator"])

        # Act
        _communicator, connected, code = await self._connect(self.other_user)

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_NOT_FOUND)

    async def test_hub_editor_passes_the_rollout_gate(self):
        # Arrange
        user_model = get_user_model()

        # Act
        with patch.object(user_model, "is_hub_editor", return_value=True):
            communicator, connected, _detail = await self._connect(
                self.other_user, conversation_id=self.other_conversation.id
            )

        # Assert
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_owner_connects_and_receives_published_events(self):
        # Arrange
        communicator, connected, subprotocol = await self._connect(self.user)
        self.assertTrue(connected)
        self.assertEqual(subprotocol, "Token")
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
        self.assertEqual(json.loads(await communicator.receive_from()), event)
        await communicator.disconnect()
