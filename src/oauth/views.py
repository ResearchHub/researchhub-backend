import json

from allauth.socialaccount.helpers import render_authentication_error
from allauth.socialaccount.models import SocialLogin, SocialAccount
from allauth.socialaccount.providers.base import ProviderException
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.orcid.views import OrcidOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import (
    OAuth2Error,
    OAuth2Client
)
from allauth.socialaccount.providers.oauth2.views import (
    AuthError,
    OAuth2CallbackView,
    PermissionDenied,
    RequestException
)
from allauth.utils import get_request_param, get_user_model
from allauth.account.signals import user_signed_up, user_logged_in
from allauth.account import app_settings

from rest_auth.registration.views import SocialLoginView
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from django.dispatch import receiver
from django.http import HttpRequest
from django.utils.datastructures import MultiValueDictKeyError
from django.utils.translation import ugettext_lazy as _

from .helpers import complete_social_login
from .exceptions import LoginError
from researchhub.settings import (
    GOOGLE_REDIRECT_URL,
    ORCID_REDIRECT_URL,
    SOCIALACCOUNT_PROVIDERS
)
from utils import sentry
from utils.http import http_request, POST


class SocialLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=False, allow_blank=True)
    code = serializers.CharField(required=False, allow_blank=True)

    def _get_request(self):
        request = self.context.get('request')
        if not isinstance(request, HttpRequest):
            request = request._request
        return request

    def get_social_login(self, adapter, app, token, response):
        """
        :param adapter: allauth.socialaccount Adapter subclass.
            Usually OAuthAdapter or Auth2Adapter
        :param app: `allauth.socialaccount.SocialApp` instance
        :param token: `allauth.socialaccount.SocialToken` instance
        :param response: Provider's response for OAuth1. Not used in the
        :returns: A populated instance of the
            `allauth.socialaccount.SocialLoginView` instance
        """
        request = self._get_request()
        social_login = adapter.complete_login(
            request,
            app,
            token,
            response=response
        )
        social_login.token = token
        return social_login

    def validate(self, attrs):
        view = self.context.get('view')
        request = self._get_request()

        if not view:
            raise serializers.ValidationError(
                _("View is not defined, pass it as a context variable")
            )

        adapter_class = getattr(view, 'adapter_class', None)
        if not adapter_class:
            raise serializers.ValidationError(
                _("Define adapter_class in view")
            )

        adapter = adapter_class(request)
        app = adapter.get_provider().get_app(request)

        # More info on code vs access_token
        # http://stackoverflow.com/questions/8666316/facebook-oauth-2-0-code-and-token

        # Case 1: We received the access_token
        if attrs.get('access_token'):
            access_token = attrs.get('access_token')

        # Case 2: We received the authorization code
        elif attrs.get('code'):
            self.callback_url = getattr(view, 'callback_url', None)
            self.client_class = getattr(view, 'client_class', None)

            if not self.callback_url:
                error = serializers.ValidationError(
                    _("Define callback_url in view")
                )
                sentry.log_error(error)
                raise error
            if not self.client_class:
                error = serializers.ValidationError(
                    _("Define client_class in view")
                )
                sentry.log_error(error)
                raise error

            code = attrs.get('code')

            provider = adapter.get_provider()
            scope = provider.get_scope(request)
            client = self.client_class(
                request,
                app.client_id,
                app.secret,
                adapter.access_token_method,
                adapter.access_token_url,
                self.callback_url,
                scope
            )
            token = client.get_access_token(code)
            access_token = token['access_token']

        else:
            raise serializers.ValidationError(
                _("Incorrect input. access_token or code is required."))

        social_token = adapter.parse_token({'access_token': access_token})
        social_token.app = app

        try:
            login = self.get_social_login(
                adapter,
                app,
                social_token,
                access_token
            )
            complete_social_login(request, login)
        except Exception as e:
            error = LoginError(e, 'Login failed')
            sentry.log_error(error, base_error=e)
            raise serializers.ValidationError(_("Incorrect value"))

        if not login.is_existing:
            # We have an account already signed up in a different flow
            # with the same email address: raise an exception.
            # This needs to be handled in the frontend. We can not just
            # link up the accounts due to security constraints
            if app_settings.UNIQUE_EMAIL:
                # Do we have an account already with this email address?
                account_exists = get_user_model().objects.filter(
                    email=login.user.email,
                ).exists()
                if account_exists:
                    sentry.log_info('User already registered with this e-mail')
                    raise serializers.ValidationError(
                        _("User already registered with this e-mail address.")
                    )

            login.lookup()
            login.save(request, connect=True)

        attrs['user'] = login.account.user

        return attrs


class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = GOOGLE_REDIRECT_URL
    client_class = OAuth2Client
    serializer_class = SocialLoginSerializer

# TODO: Use this one instead?
# class OrcidLogin(SocialLoginView):
#     adapter_class = OrcidOAuth2Adapter
#     callback_url = ORCID_REDIRECT_URL
#     client_class = OAuth2Client
#     serializer_class = SocialLoginSerializer


class OrcidLogin(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, format='json'):
        self.auth_code = self._parse_code(request.query_params)
        if not self.auth_code:
            return Response('Did not find code', status=400)
        else:
            response = self._request_access_token()

        return Response(f'response: {response}')

    def _parse_code(self, query_params):
        try:
            return query_params['code']
        except MultiValueDictKeyError as e:
            error = LoginError(e, 'Did not find code in query params')
            sentry.log_error(error)
            return None

    def _request_access_token(self):
        url = self._get_access_token_url()
        data = self._build_access_token_request_data()
        headers = {'accept': 'application/json'}
        return http_request(POST, url, data=data, headers=headers)

    def _get_access_token_url(self):
        return f'https://orcid.org/oauth/token'

    def _build_access_token_request_data(self):
        data = {
            'client_id': SOCIALACCOUNT_PROVIDERS['orcid']['APP']['client_id'],
            'client_secret': SOCIALACCOUNT_PROVIDERS['orcid']['APP']['secret'],
            'grant_type': 'authorization_code',
            'code': self.auth_code,
            'redirect_uri': ORCID_REDIRECT_URL,
        }
        return json.dumps(data)


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
            access_token = client.get_access_token(request.GET['code'])
            token = self.adapter.parse_token(access_token)
            token.app = app
            login = self.adapter.complete_login(request,
                                                app,
                                                token,
                                                response=access_token)
            login.token = token
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
                exception=e)


google_callback = CallbackView.adapter_view(GoogleOAuth2Adapter)
orcid_callback = CallbackView.adapter_view(OrcidOAuth2Adapter)


@receiver(user_signed_up)
@receiver(user_logged_in)
def user_signed_up_(request, user, **kwargs):
    """After a user signs up with social account, set their profile image"""

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
