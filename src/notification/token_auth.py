from channels.auth import AuthMiddlewareStack
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from rest_framework.authtoken.models import Token


class TokenAuthMiddleware(BaseMiddleware):
    """
    Token authorization middleware for Django Channels 3
    """

    def __init__(self, inner):
        super().__init__(inner)

    async def __call__(self, scope, receive, send):
        close_old_connections()
        headers = dict(scope["headers"])
        try:
            if b"sec-websocket-protocol" in headers:
                token = headers[b"sec-websocket-protocol"].decode().split(", ")
                token_name, token_key = token
                if token_name == "Token":
                    token = await Token.objects.get(key=token_key)
                    scope["user"] = token.user
        except Token.DoesNotExist:
            scope["user"] = AnonymousUser()
        return await super().__call__(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    return TokenAuthMiddleware(AuthMiddlewareStack(inner))
