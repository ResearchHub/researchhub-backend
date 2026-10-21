from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView
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
