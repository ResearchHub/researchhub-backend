from allauth.socialaccount.models import SocialLogin, SocialAccount
from allauth.account import app_settings
from allauth.utils import (
    get_user_model,
    email_address_exists
)
from rest_framework import serializers

from django.http import HttpRequest
from django.utils.translation import ugettext_lazy as _
from django.urls.exceptions import NoReverseMatch

from elasticsearch.exceptions import ConnectionTimeout

from oauth.serializers import *
from oauth.adapters import GoogleOAuth2AdapterIdToken
from oauth.helpers import complete_social_login
from oauth.exceptions import LoginError
from oauth.utils import get_orcid_names
from researchhub.settings import GOOGLE_REDIRECT_URL, GOOGLE_YOLO_REDIRECT_URL
from user.models import Author, User
from user.utils import merge_author_profiles
from utils import sentry
from utils.siftscience import events_api, update_user_risk_score, check_user_risk
from analytics.models import WebsiteVisits

from django.contrib.gis.geoip2 import GeoIP2
geo = GeoIP2()

class SocialLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=False, allow_blank=True)
    code = serializers.CharField(required=False, allow_blank=True)
    credential = serializers.CharField(required=False, allow_blank=True)
    uuid = serializers.CharField(required=False, allow_blank=True)
    referral_code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )

    def _get_request(self):
        request = self.context.get('request')
        if not isinstance(request, HttpRequest):
            request = request._request
        return request

    def _delete_user_account(self, user, error=None):
        user_email = user.email
        email_exists = email_address_exists(user_email)
        if email_exists:
            user = User.objects.get(email=user_email)
            social_account_exists = SocialAccount.objects.filter(
                user=user
            ).exists()
            if not social_account_exists:
                deletion_info = user.delete()
                sentry.log_info(deletion_info, error=error)
                return True
        return False

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

    def validate(self, attrs, retry=0):
        view = self.context.get('view')
        request = self._get_request()

        if not view:
            error = serializers.ValidationError(
                _("View is not defined, pass it as a context variable")
            )
            sentry.log_error(error)
            raise error

        adapter_class = getattr(view, 'adapter_class', None)
        if not adapter_class:
            error = serializers.ValidationError(
                _("Define adapter_class in view")
            )
            sentry.log_error(error)
            raise error

        adapter = adapter_class(request)
        app = adapter.get_provider().get_app(request)

        # More info on code vs access_token
        # http://stackoverflow.com/questions/8666316/facebook-oauth-2-0-code-and-token

        credential = attrs.get('credential')

        # Case 1: We received the access_token
        if attrs.get('access_token') or credential:
            access_token = attrs.get('access_token')
            if credential:
                access_token = credential

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
            error = serializers.ValidationError(
                _("Incorrect input. access_token or code is required."))
            sentry.log_error(error)
            raise serializers.ValidationError(
                _("Incorrect input. access_token or code is required."))

        social_token = adapter.parse_token({'access_token': access_token})
        social_token.app = app

        login = None
        try:
            login = self.get_social_login(
                adapter,
                app,
                social_token,
                access_token
            )
            complete_social_login(request, login)
        except ConnectionTimeout:
            pass
        except NoReverseMatch as e:
            if 'account_inactive' in str(e):
                login_user = login.account.user
                tracked_login = events_api.track_login(
                    login_user,
                    '$failure',
                    request
                )
                update_user_risk_score(login_user, tracked_login)
                raise LoginError(None, 'Account is suspended')
        except Exception as e:
            error = LoginError(e, 'Login failed')
            sentry.log_info(error, error=e)
            if login:
                deleted = self._delete_user_account(login.user, error=e)
                if deleted and retry < 3:
                    return self.validate(attrs, retry=retry+1)
            sentry.log_error(error, base_error=e)
            raise serializers.ValidationError(_("Incorrect value"))

        if login and not login.is_existing:
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
                    deleted = self._delete_user_account(login.user)
                    if deleted and retry < 3:
                        return self.validate(attrs, retry=retry+1)
                    raise serializers.ValidationError(
                        _("User already registered with this e-mail address.")
                    )

            login.lookup()
            login.save(request, connect=True)

        login_user = login.account.user
        attrs['user'] = login_user
        tracked_login = events_api.track_login(login_user, '$success', request)
        update_user_risk_score(login_user, tracked_login)

        try:
            visits = WebsiteVisits.objects.get(uuid=attrs['uuid'])
            visits.user = attrs['user']
            visits.save()
        except Exception as e:
            print(e)
            pass

        try:
            referral_code = attrs.get('referral_code')
            if referral_code:
                referral_user = User.objects.get(referral_code=referral_code)
                user = attrs['user']
                if referral_code and not user.invited_by and referral_user.id != user.id:
                    user.invited_by = referral_user
                    user.save()
        except Exception as e:
            print(e)
            sentry.log_error(e)
            pass


        request = self._get_request()
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        user = attrs['user']
        check_user_risk(user)

        if user.is_authenticated and not user.probable_spammer:
            try:
                country = geo.country(ip)
                user.country_code = country.get('country_code')
                user.save()
                if country.get('country_code') in ['ID']:
                    user.set_probable_spammer()
            except Exception as e:
                print(e)
                sentry.log_error(e)

        return attrs
