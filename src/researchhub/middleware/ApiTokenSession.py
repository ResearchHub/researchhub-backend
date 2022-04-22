from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication
from rest_framework_api_key.permissions import KeyParser

from researchhub.settings import API_KEY_CUSTOM_HEADER


def get_user(request):
    from user.models import UserApiToken

    key_parser = KeyParser()
    user = None
    key = key_parser.get(request)
    try:
        token = UserApiToken.objects.get_from_key(key)
        user = token.user
    except UserApiToken.DoesNotExist:
        raise exceptions.PermissionDenied("Invalid API key")

    request._cached_user = user
    return user, key


class UserApiTokenAuth(TokenAuthentication):
    def authenticate(self, request):
        if API_KEY_CUSTOM_HEADER in request.META:
            user, key = get_user(request)
            return user, key
        else:
            return super().authenticate(request)
