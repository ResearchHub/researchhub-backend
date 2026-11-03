from functools import wraps

from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
from django.http import Http404
from oauth2_provider.views import OAuthServerMetadataView
from rest_framework.response import Response

from oauth.adapters import XOAuth2Adapter
from oauth.serializers import SocialLoginSerializer, XLoginSerializer


# Google login -> SocialLoingSerializer
# -> adaptor functions are called in "#complete_login"
class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    serializer_class = SocialLoginSerializer


class XLogin(SocialLoginView):
    adapter_class = XOAuth2Adapter
    serializer_class = XLoginSerializer

    def get_response(self) -> Response:
        """Return the app-bound X token for NextAuth's server-side profile lookup."""
        response = super().get_response()
        response.data["access_token"] = self.serializer.validated_data["access_token"]
        return response


def oauth_enabled(view):
    """
    Hides an OAuth endpoint while `OAUTH_ENABLED` is off.
    """

    # wraps() keeps view attributes such as DOT's `csrf_exempt`
    @wraps(view)
    def wrapped_view(request, *args, **kwargs):
        if not settings.OAUTH_ENABLED:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapped_view


class AuthorizationServerMetadataView(OAuthServerMetadataView):
    """
    Returns OAuth 2.0 authorization server metadata (RFC 8414).
    """

    def _get_endpoint_url(self, request, view_name, required=False):
        if view_name == "authorize":
            # The consent page is hosted on the frontend:
            return f"{settings.BASE_FRONTEND_URL}/oauth/authorize"
        return super()._get_endpoint_url(request, view_name, required)
