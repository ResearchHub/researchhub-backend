from rest_framework import HTTP_HEADER_ENCODING, exceptions
from rest_framework.authentication import TokenAuthentication
from rest_framework_api_key.permissions import KeyParser

from researchhub.settings import API_KEY_CUSTOM_HEADER
from utils.sentry import log_error


def get_organization_header(request):
    """
    Taken from DRF source code

    Return request's 'X-organization-id:' header, as a bytestring.

    Hide some test client ickyness where the header can be unicode.
    """
    org_id = request.META.get("HTTP_X_ORGANIZATION_ID", b"")
    if isinstance(org_id, str):
        # Work around django test client oddness
        org_id = org_id.encode(HTTP_HEADER_ENCODING)
    return org_id


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
    def _set_user_organization(self, request, user):
        try:
            org_id = get_organization_header(request)
            if org_id:
                from user.models import Organization

                org = Organization.objects.get(id=org_id)
                if org.org_has_user(user):
                    request.organization = org
                else:
                    request.organization = None
            else:
                request.organization = None
        except Organization.DoesNotExist:
            request.organization = None
        except Exception as e:
            request.organization = None
            log_error(e)

    def authenticate(self, request):
        if API_KEY_CUSTOM_HEADER in request.META:
            user, key = get_user(request)
        else:
            res = super().authenticate(request)
            if res:
                user, key = super().authenticate(request)
            else:
                return res

        self._set_user_organization(request, user)
        return user, key
