import requests

from allauth.socialaccount.helpers import render_authentication_error
from allauth.socialaccount.models import SocialLogin, SocialAccount
from allauth.socialaccount.providers.base import ProviderException
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from allauth.socialaccount.providers.orcid.views import OrcidOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import (
    OAuth2Error,
    OAuth2Client
)
from allauth.socialaccount.providers.oauth2.views import (
    AuthError,
    OAuth2LoginView,
    OAuth2CallbackView,
    PermissionDenied,
    RequestException
)
from allauth.utils import (
    get_request_param,
)
from allauth.account.signals import user_signed_up, user_logged_in
from allauth.account import app_settings

from rest_auth.registration.views import SocialLoginView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from django.dispatch import receiver

from mailchimp_marketing import Client

from oauth.serializers import SocialLoginSerializer
from oauth.adapters import GoogleOAuth2AdapterIdToken
from oauth.helpers import complete_social_login
from oauth.exceptions import LoginError
from oauth.utils import get_orcid_names
from researchhub.settings import (
    GOOGLE_REDIRECT_URL,
    GOOGLE_YOLO_REDIRECT_URL,
    keys,
    MAILCHIMP_SERVER,
    MAILCHIMP_LIST_ID,
    RECAPTCHA_SECRET_KEY,
    RECAPTCHA_VERIFY_URL
)
from user.models import Author
from user.utils import merge_author_profiles
from utils import sentry
from utils.http import http_request, RequestMethods
from utils.throttles import captcha_unlock
from utils.siftscience import events_api


@api_view([RequestMethods.POST])
@permission_classes([AllowAny])
def captcha_verify(request):
    verify_request = requests.post(
        RECAPTCHA_VERIFY_URL,
        {
            'secret': RECAPTCHA_SECRET_KEY,
            'response': request.data.get('response')
        }
    )
    status = verify_request.status_code
    req_json = verify_request.json()

    data = {'success': req_json.get('success')}
    if req_json.get("error-codes"):
        data['errors'] = req_json.get('error-codes')

    if data['success']:
        # turn off throttling
        captcha_unlock(request)

    return Response(data, status=status)


class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = GOOGLE_REDIRECT_URL
    client_class = OAuth2Client
    serializer_class = SocialLoginSerializer


class GoogleYoloLogin(SocialLoginView):
    adapter_class = GoogleOAuth2AdapterIdToken
    callback_url = GOOGLE_YOLO_REDIRECT_URL
    client_class = OAuth2Client
    serializer_class = SocialLoginSerializer


class CallbackView(OAuth2CallbackView):
    """
    This class is copied from allauth/socialaccount/providers/oauth2/views.py
    but uses a custom method for `complete_social_login`
    """
    permission_classes = (AllowAny,)

    def dispatch(self, request, *args, **kwargs):
        if 'error' in request.GET or 'code' not in request.GET:
            # Distinguish cancel from error
            auth_error = request.GET.get('error', None)
            if auth_error == self.adapter.login_cancelled_error:
                error = AuthError.CANCELLED
            else:
                error = AuthError.UNKNOWN
            return render_authentication_error(
                request,
                self.adapter.provider_id,
                error=error)
        app = self.adapter.get_provider().get_app(self.request)
        client = self.get_client(request, app)
        try:
            try:
                access_token = client.get_access_token(request.GET['code'])
            except Exception:
                access_token = client.get_access_token(
                    request.GET['credential']
                )
            token = self.adapter.parse_token(access_token)
            token.app = app
            login = self.adapter.complete_login(request,
                                                app,
                                                token,
                                                response=access_token)
            login.token = token
            if self.adapter.provider_id != OrcidProvider.id:
                if self.adapter.supports_state:
                    login.state = SocialLogin \
                        .verify_and_unstash_state(
                            request,
                            get_request_param(request, 'state'))
                else:
                    login.state = SocialLogin.unstash_state(request)
            return complete_social_login(request, login)
        except (PermissionDenied,
                OAuth2Error,
                RequestException,
                ProviderException) as e:
            return render_authentication_error(
                request,
                self.adapter.provider_id,
                exception=e
            )


google_callback = CallbackView.adapter_view(GoogleOAuth2Adapter)
google_yolo_login = OAuth2LoginView.adapter_view(GoogleOAuth2AdapterIdToken)
google_yolo_callback = CallbackView.adapter_view(GoogleOAuth2AdapterIdToken)
orcid_callback = CallbackView.adapter_view(OrcidOAuth2Adapter)


@api_view([RequestMethods.POST])
@permission_classes([IsAuthenticated])
def orcid_connect(request):
    success = False
    status = 400

    try:
        orcid = request.data.get('orcid')
        access_token = request.data.get('access_token')
        url = f'https://pub.orcid.org/v3.0/{orcid}/record'
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
        # Raise for status because we need to make sure we can authenticate
        # correctly with orcid. Without this check, anyone could make a post
        # request to connect any other orcid account to their own.
        response = http_request(RequestMethods.GET, url=url, headers=headers)
        response.raise_for_status()
        user = request.user

        save_orcid_author(user, orcid, response.json())
        events_api.track_account(user, request, update=True)

        success = True
        status = 201
        data = {
            'success': success,
            'orcid_profile': f'https://orcid.org/{orcid}'
        }
    except Exception as e:
        data = str(e)
        sentry.log_error(e)
        print(e)

    return Response(data, status=status)


def save_orcid_author(user, orcid_id, orcid_data):
    orcid_account = SocialAccount.objects.create(
        user=user,
        uid=orcid_id,
        provider=OrcidProvider.id,
        extra_data=orcid_data
    )
    update_author_profile(user, orcid_id, orcid_data, orcid_account)


def update_author_profile(user, orcid_id, orcid_data, orcid_account):
    first_name, last_name = get_orcid_names(orcid_data)

    try:
        author = Author.objects.get(orcid_id=orcid_id)
    except Author.DoesNotExist:
        user.author_profile.orcid_id = orcid_id
    else:
        user.author_profile = merge_author_profiles(
            user.author_profile,
            author
        )

    user.author_profile.orcid_account = orcid_account
    user.author_profile.first_name = first_name
    user.author_profile.last_name = last_name
    user.author_profile.save()
    user.save()


@receiver(user_signed_up)
@receiver(user_logged_in)
def user_signed_up_(request, user, **kwargs):
    """
    After a user signs up with social account, set their profile image.
    """

    queryset = SocialAccount.objects.filter(
        provider='google',
        user=user
    )

    if queryset.exists():
        if queryset.count() > 1:
            raise Exception(
                f'Expected 1 item in the queryset. Found {queryset.count()}.'
            )

        google_account = queryset.first()
        url = google_account.extra_data.get('picture', None)

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
    mailchimp.set_config({
        'api_key': keys.MAILCHIMP_KEY,
        'server': MAILCHIMP_SERVER
    })

    try:
        member_info = {'email_address': user.email, 'status': 'subscribed'}
        mailchimp.lists.add_list_member(MAILCHIMP_LIST_ID, member_info)
    except Exception as error:
        sentry.log_error(error, message=error.text)
