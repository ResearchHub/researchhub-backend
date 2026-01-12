import requests
from allauth.account.signals import user_logged_in, user_signed_up
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from dj_rest_auth.views import LoginView
from django.dispatch import receiver
from mailchimp_marketing import Client
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from analytics.amplitude import Amplitude
from oauth.serializers import SocialLoginSerializer
from researchhub.settings import (
    GOOGLE_REDIRECT_URL,
    MAILCHIMP_KEY,
    MAILCHIMP_LIST_ID,
    MAILCHIMP_SERVER,
    RECAPTCHA_SECRET_KEY,
    RECAPTCHA_VERIFY_URL,
)
from utils import sentry
from utils.http import RequestMethods
from utils.throttles import captcha_unlock


@api_view([RequestMethods.POST])
@permission_classes([AllowAny])
def captcha_verify(request):
    verify_request = requests.post(
        RECAPTCHA_VERIFY_URL,
        {"secret": RECAPTCHA_SECRET_KEY, "response": request.data.get("response")},
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
    callback_url = GOOGLE_REDIRECT_URL
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


@receiver(user_signed_up)
def mailchimp_add_user(request, user, **kwargs):
    """Adds user email to MailChimp"""
    mailchimp = Client()
    mailchimp.set_config({"api_key": MAILCHIMP_KEY, "server": MAILCHIMP_SERVER})

    try:
        member_info = {"email_address": user.email, "status": "subscribed"}
        mailchimp.lists.add_list_member(MAILCHIMP_LIST_ID, member_info)
    except Exception as error:
        sentry.log_error(error, message=error.text)


@receiver(user_signed_up)
def track_user_signup(request, user, **kwargs):
    class temp_res:
        def __init__(self, user):
            self.data = {"id": user.id}

    class temp_view:
        def __init__(self):
            self.__dict__ = {"basename": "user", "action": "signup"}

    try:
        request.user = user
        res = temp_res(user)
        view = temp_view()
        amp = Amplitude()
        amp.build_hit(res, view, request, **kwargs)
    except Exception as e:
        sentry.log_error(e)
