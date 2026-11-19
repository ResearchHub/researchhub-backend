from datetime import timedelta

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.authtoken.models import Token

from user.services.auth_token_service import AuthTokenService

CLOSE_UNAUTHENTICATED = 4401
TOKEN_RECHECK_INTERVAL = timedelta(minutes=1)


@database_sync_to_async
def _authenticate(key: str) -> Token | None:
    service = AuthTokenService()
    token = service.get_active_token(key)
    if token is not None:
        service.record_use(token)
    return token


@database_sync_to_async
def _is_token_active(key: str) -> bool:
    return AuthTokenService().get_active_token(key) is not None


def _token_key(scope) -> str | None:
    protocols = dict(scope["headers"]).get(b"sec-websocket-protocol", b"")
    parts = protocols.decode("latin-1").split(", ")
    if len(parts) == 2 and parts[0] == "Token":
        return parts[1]
    return None


class _TokenCheckedSend:
    def __init__(self, key: str, send):
        self.key = key
        self.send = send
        self.closed = False
        self.next_check = timezone.now() + TOKEN_RECHECK_INTERVAL

    async def __call__(self, message):
        if self.closed:
            return
        if message["type"] == "websocket.send" and await self._token_lapsed():
            self.closed = True
            message = {"type": "websocket.close", "code": CLOSE_UNAUTHENTICATED}
        await self.send(message)

    async def _token_lapsed(self) -> bool:
        now = timezone.now()
        if now < self.next_check:
            return False
        self.next_check = now + TOKEN_RECHECK_INTERVAL
        return not await _is_token_active(self.key)


class TokenAuthMiddleware(BaseMiddleware):
    """
    Token authorization middleware for Django Channels 3
    """

    async def __call__(self, scope, receive, send):
        key = _token_key(scope)
        if key is not None:
            token = await _authenticate(key)
            if token is None:
                scope["user"] = AnonymousUser()
            else:
                scope["user"] = token.user
                send = _TokenCheckedSend(key, send)
        return await super().__call__(scope, receive, send)


def TokenAuthMiddlewareStack(inner):  # noqa: N802
    return TokenAuthMiddleware(AuthMiddlewareStack(inner))
