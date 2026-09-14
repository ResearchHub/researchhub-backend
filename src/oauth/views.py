from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from dj_rest_auth.registration.views import SocialLoginView

from oauth.serializers import SocialLoginSerializer


# Google login -> SocialLoingSerializer
# -> adaptor functions are called in "#complete_login"
class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    serializer_class = SocialLoginSerializer
