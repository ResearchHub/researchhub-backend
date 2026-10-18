"""WebSocket consumer admission and event forwarding for Expert Finder."""

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
from research_ai.models import ExpertSearch
from research_ai.services.expert_finder.events import EVENT_TYPE, search_group

application = URLRouter(research_ai.routing.websocket_urlpatterns)


class ExpertFinderConsumerTests(TransactionTestCase):
    """Admission mirrors expert-finder REST; events are forwarded verbatim."""

    def setUp(self):
        user_model = get_user_model()
        self.moderator = user_model.objects.create_user(
            username="mod@researchhub_test.com",
            password="password",
            email="mod@researchhub_test.com",
            moderator=True,
        )
        self.regular = user_model.objects.create_user(
            username="user@researchhub_test.com",
            password="password",
            email="user@researchhub_test.com",
        )
        self.search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Live updates",
            status=ExpertSearch.Status.PENDING,
        )

    async def _connect(self, user, *, search_id=None):
        search_id = self.search.id if search_id is None else search_id
        communicator = WebsocketCommunicator(
            application, f"/ws/expert-finder/searches/{search_id}/"
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

    async def test_regular_user_is_rejected(self):
        # Act
        _communicator, connected, code = await self._connect(self.regular)

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_FORBIDDEN)

    async def test_missing_search_reads_as_not_found(self):
        # Act
        _communicator, connected, code = await self._connect(
            self.moderator, search_id=999999
        )

        # Assert
        self.assertFalse(connected)
        self.assertEqual(code, CLOSE_NOT_FOUND)

    async def test_hub_editor_can_connect(self):
        # Arrange
        user_model = get_user_model()

        # Act
        with patch.object(user_model, "is_hub_editor", return_value=True):
            communicator, connected, _detail = await self._connect(self.regular)

        # Assert
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_moderator_connects_and_receives_published_events(self):
        # Arrange
        communicator, connected, subprotocol = await self._connect(self.moderator)
        self.assertTrue(connected)
        self.assertEqual(subprotocol, "Token")
        event = {
            "search_id": self.search.id,
            "kind": "experts_found",
            "expert_count": 3,
        }

        # Act
        await get_channel_layer().group_send(
            search_group(self.search.id),
            {"type": EVENT_TYPE, "data": event},
        )

        # Assert
        self.assertEqual(json.loads(await communicator.receive_from()), event)
        await communicator.disconnect()
