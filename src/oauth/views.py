import requests
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from oauth.serializers import SocialLoginSerializer
from utils.http import RequestMethods
from utils.throttles import captcha_unlock


@api_view([RequestMethods.POST])
@permission_classes([AllowAny])
def captcha_verify(request):
    verify_request = requests.post(
        settings.RECAPTCHA_VERIFY_URL,
        {
            "secret": settings.RECAPTCHA_SECRET_KEY,
            "response": request.data.get("response"),
        },
    )
    status = verify_request.status_code
    req_json = verify_request.json()

    data = {"success": req_json.get("success")}
    if req_json.get("error-codes"):
        data["errors"] = req_json.get("error-codes")

    if data["success"]:
        # turn off throttling
        captcha_unlock(request)

    return Response(data, status=status)


# Google login -> SocialLoingSerializer -> adaptor functions are called in "#complete_login"
class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = settings.GOOGLE_REDIRECT_URL
    client_class = OAuth2Client
    serializer_class = SocialLoginSerializer
