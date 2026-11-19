from datetime import timedelta
from unittest.mock import patch

from asgiref.testing import ApplicationCommunicator
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token

from researchhub.token_auth import CLOSE_UNAUTHENTICATED, TokenAuthMiddleware
from user.models import AuthTokenActivity
from user.services.auth_token_service import AuthTokenService


class RecordingApp:
    def __init__(self):
        self.user = None

    async def __call__(self, scope, receive, send):
        self.user = scope.get("user")
        await receive()
        await send({"type": "websocket.accept", "subprotocol": "Token"})
        while True:
            message = await receive()
            if message["type"] == "websocket.disconnect":
                return
            await send({"type": "websocket.send", "text": message["text"]})


class TokenAuthMiddlewareTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="socket-user@researchhub_test.com",
            email="socket-user@researchhub_test.com",
            password="password",
        )
        self.token = AuthTokenService().issue(self.user)
        self.app = RecordingApp()

    def expire_token(self):
        AuthTokenActivity.objects.filter(token=self.token).update(
            issued_at=timezone.now() - settings.AUTH_TOKEN_ABSOLUTE_LIFETIME
        )

    def communicator(self, protocol=None):
        protocol = protocol or f"Token, {self.token.key}".encode()
        scope = {
            "type": "websocket",
            "path": "/ws/",
            "headers": [(b"sec-websocket-protocol", protocol)],
        }
        return ApplicationCommunicator(TokenAuthMiddleware(self.app), scope)

    async def connect(self, communicator):
        await communicator.send_input({"type": "websocket.connect"})
        return await communicator.receive_output()

    async def disconnect(self, communicator):
        await communicator.send_input({"type": "websocket.disconnect", "code": 1000})
        await communicator.wait()

    async def test_active_token_resolves_user(self):
        # Arrange
        communicator = self.communicator()

        # Act
        await self.connect(communicator)

        # Assert
        self.assertEqual(self.app.user.pk, self.user.pk)
        await self.disconnect(communicator)

    async def test_expired_token_is_anonymous(self):
        # Arrange
        await database_sync_to_async(self.expire_token)()
        communicator = self.communicator()

        # Act
        await self.connect(communicator)

        # Assert
        self.assertTrue(self.app.user.is_anonymous)
        await self.disconnect(communicator)

    async def test_unknown_token_is_anonymous(self):
        # Arrange
        communicator = self.communicator(b"Token, unknown")

        # Act
        await self.connect(communicator)

        # Assert
        self.assertTrue(self.app.user.is_anonymous)
        await self.disconnect(communicator)

    async def test_inactive_user_is_anonymous(self):
        # Arrange
        await database_sync_to_async(
            get_user_model().objects.filter(pk=self.user.pk).update
        )(is_active=False)
        communicator = self.communicator()

        # Act
        await self.connect(communicator)

        # Assert
        self.assertTrue(self.app.user.is_anonymous)
        await self.disconnect(communicator)

    async def test_malformed_protocol_header_does_not_authenticate(self):
        # Arrange
        communicator = self.communicator(b"Token")

        # Act
        await self.connect(communicator)

        # Assert
        self.assertIsNone(self.app.user)
        await self.disconnect(communicator)

    @patch("researchhub.token_auth.TOKEN_RECHECK_INTERVAL", timedelta(0))
    async def test_open_socket_stays_open_while_token_is_active(self):
        # Arrange
        communicator = self.communicator()
        await self.connect(communicator)

        # Act
        await communicator.send_input({"type": "websocket.receive", "text": "ping"})
        output = await communicator.receive_output()

        # Assert
        self.assertEqual(output, {"type": "websocket.send", "text": "ping"})
        await self.disconnect(communicator)

    @patch("researchhub.token_auth.TOKEN_RECHECK_INTERVAL", timedelta(0))
    async def test_open_socket_closes_once_token_expires(self):
        # Arrange
        communicator = self.communicator()
        await self.connect(communicator)
        await database_sync_to_async(self.expire_token)()

        # Act
        await communicator.send_input({"type": "websocket.receive", "text": "ping"})
        output = await communicator.receive_output()

        # Assert
        self.assertEqual(
            output, {"type": "websocket.close", "code": CLOSE_UNAUTHENTICATED}
        )
        await self.disconnect(communicator)

    @patch("researchhub.token_auth.TOKEN_RECHECK_INTERVAL", timedelta(0))
    async def test_open_socket_closes_once_token_is_revoked(self):
        # Arrange
        communicator = self.communicator()
        await self.connect(communicator)
        await database_sync_to_async(Token.objects.filter(key=self.token.key).delete)()

        # Act
        await communicator.send_input({"type": "websocket.receive", "text": "ping"})
        output = await communicator.receive_output()

        # Assert
        self.assertEqual(output["type"], "websocket.close")
        await self.disconnect(communicator)
