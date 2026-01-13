import requests
from allauth.account.signals import user_logged_in, user_signed_up
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from dj_rest_auth.views import LoginView
from django.conf import settings
from django.dispatch import receiver
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


class EmailLoginView(LoginView):
    def post(self, request, *args, **kwargs):
        res = super().post(request, *args, **kwargs)
        return res


@receiver(user_signed_up)
@receiver(user_logged_in)
def user_signed_up_(request, user, **kwargs):
    """
    After a user signs up with social account, set their profile image.
    """
    queryset = SocialAccount.objects.filter(provider="google", user=user)

    if queryset.exists():
        if queryset.count() > 1:
            raise Exception(
                f"Expected 1 item in the queryset. Found {queryset.count()}."
            )

        google_account = queryset.first()
        url = google_account.extra_data.get("picture", None)

        if user.author_profile and not user.author_profile.profile_image:
            user.author_profile.profile_image = url
            user.author_profile.save()
        return None

    else:
        return None
