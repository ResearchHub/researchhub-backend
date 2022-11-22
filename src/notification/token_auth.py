from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from rest_framework.authtoken.models import Token

from user.models import User


@database_sync_to_async
def get_user(token_key):
    token = Token.objects.get(key=token_key)
    return token.user


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
                    token = await Token.objects.aget(key=token_key)
                    user = await User.objects.aget(auth_token=token)
                    # user = await get_user(token_key)
                    scope["user"] = user
        except Token.DoesNotExist:
            scope["user"] = AnonymousUser()
        return await super().__call__(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    return TokenAuthMiddleware(AuthMiddlewareStack(inner))
