from time import time

from allauth.account import app_settings
from allauth.socialaccount.models import SocialAccount
from allauth.utils import email_address_exists, get_user_model
from django.http import HttpRequest
from django.urls.exceptions import NoReverseMatch
from django.utils.translation import gettext_lazy as _
from elasticsearch.exceptions import ConnectionTimeout
from rest_framework import serializers

from analytics.models import WebsiteVisits
from oauth.exceptions import LoginError
from oauth.helpers import complete_social_login
from oauth.serializers import *
from reputation import distributions
from reputation.distributor import Distributor
from reputation.models import Distribution
from researchhub.settings import REFERRAL_PROGRAM
from user.models import User
from utils import sentry
from utils.siftscience import check_user_risk, events_api, update_user_risk_score


class SocialLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=False, allow_blank=True)
    code = serializers.CharField(required=False, allow_blank=True)
    credential = serializers.CharField(required=False, allow_blank=True)
    uuid = serializers.CharField(required=False, allow_blank=True)
    referral_code = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    def _get_request(self):
        request = self.context.get("request")
        if not isinstance(request, HttpRequest):
            request = request._request
        return request

    def _delete_user_account(self, user, error=None):
        user_email = user.email
        email_exists = email_address_exists(user_email)
        if email_exists:
            user = User.objects.get(email=user_email)
            social_account_exists = SocialAccount.objects.filter(user=user).exists()
            if not social_account_exists:
                deletion_info = user.delete()
                sentry.log_info(deletion_info, error=error)
                return True
        return False

    def validate(self, attrs, retry=0):
        view = self.context.get("view")
        request = self._get_request()

        if not view:
            error = serializers.ValidationError(
                _("View is not defined, pass it as a context variable")
            )
            sentry.log_error(error)
            raise error

        adapter_class = getattr(view, "adapter_class", None)
        if not adapter_class:
            error = serializers.ValidationError(_("Define adapter_class in view"))
            sentry.log_error(error)
            raise error

        adapter = adapter_class(request)
        app = adapter.get_provider().get_app(request)

        # More info on code vs access_token
        # http://stackoverflow.com/questions/8666316/facebook-oauth-2-0-code-and-token

        credential = attrs.get("credential")
        # Case 1: OneTap Login sends back "credential" which is a jwt encoded user data
        if credential:
            access_token = credential
        # Case 2: We received the authorization code => "Regular flow"
        elif attrs.get("code"):
            # pdb.set_trace()
            self.callback_url = getattr(view, "callback_url", None)
            self.client_class = getattr(view, "client_class", None)

            if not self.callback_url:
                error = serializers.ValidationError(_("Define callback_url in view"))
                sentry.log_error(error)
                raise error
            if not self.client_class:
                error = serializers.ValidationError(_("Define client_class in view"))
                sentry.log_error(error)
                raise error

            code = attrs.get("code")

            provider = adapter.get_provider()
            scope = provider.get_scope(request)
            client = self.client_class(
                request,
                app.client_id,
                app.secret,
                adapter.access_token_method,
                adapter.access_token_url,
                "postmessage",  # This is the callback url
                scope,
            )
            token = client.get_access_token(code)
            access_token = token["access_token"]
        # Case 3: Handle error
        else:
            error = serializers.ValidationError(
                _("Incorrect input. access_token or code is required.")
            )
            sentry.log_error(error)
            raise serializers.ValidationError(
                _("Incorrect input. access_token or code is required.")
            )

        login = None
        # executes respective adaptor's social login protocols
        login = self.handle_social_login(adapter, app, access_token)
        self.check_duplicates_then_save_social_login(request, login)

        login_user = login.account.user
        attrs["user"] = login_user
        tracked_login_w_events_api = events_api.track_login(
            login_user, "$success", request
        )
        update_user_risk_score(login_user, tracked_login_w_events_api)
        self.track_user_visit_after_login(attrs)
        self.handle_referral(attrs)
        import pdb

        pdb.set_trace()
        return attrs

    def handle_social_login(self, adapter, app, access_token):
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
            request, app, access_token, response=access_token
        )

        social_token = adapter.parse_token(
            {"access_token": access_token}
        )  # token instance
        social_token.app = app
        social_login.token = access_token

        try:
            complete_social_login(request, social_login)
        except ConnectionTimeout:
            pass
        except NoReverseMatch as e:
            if "account_inactive" in str(e):
                login_user = social_login.account.user
                tracked_login = events_api.track_login(login_user, "$failure", request)
                update_user_risk_score(login_user, tracked_login)
                raise LoginError(None, "Account is suspended")
        except Exception as e:
            error = LoginError(e, "Login failed")
            sentry.log_info(error, error=e)
            sentry.log_error(error, base_error=e)
            raise serializers.ValidationError(_("Incorrect value"))

        return social_login

    def check_duplicates_then_save_social_login(self, request, login):
        if login and not login.is_existing:
            # We have an account already signed up in a different flow
            # with the same email address: raise an exception.
            # This needs to be handled in the frontend. We can not just
            # link up the accounts due to security constraints
            if app_settings.UNIQUE_EMAIL:
                # Do we have an account already with this email address?
                account_exists = (
                    get_user_model()
                    .objects.filter(
                        email=login.user.email,
                    )
                    .exists()
                )
                if account_exists:
                    sentry.log_info("User already registered with this email")
                    # deleted = self._delete_user_account(login.user)
                    # if deleted and retry < 3:
                    #     return self.validate(attrs, retry=retry + 1)
                    raise serializers.ValidationError(
                        _("User already registered with this email address.")
                    )

            login.lookup()
            login.save(request, connect=True)

    def track_user_visit_after_login(self, attrs):
        """failure of this function is trivial"""
        try:
            visits = WebsiteVisits.objects.get(uuid=attrs.get("uuid"))
            visits.user = attrs["user"]
            visits.save()
        except Exception as e:
            print(e)
            pass

    def handle_referral(self, attrs):
        try:
            referral_code = attrs.get("referral_code")
            if referral_code:
                referral_user = User.objects.get(referral_code=referral_code)
                user = attrs["user"]

                invited_by_flag_not_set = (
                    referral_code
                    and not user.invited_by
                    and referral_user.id != user.id
                )
                if invited_by_flag_not_set:
                    user.invited_by = referral_user
                    user.save()

                    has_invited_been_paid = Distribution.objects.filter(
                        distribution_type=REFERRAL_PROGRAM["INVITED_DISTRIBUTION_TYPE"],
                        recipient_id=user.id,
                    ).exists()

                    if not has_invited_been_paid:
                        try:
                            referral_bonus = Distributor(
                                distribution=distributions.ReferralInvitedBonus,
                                recipient=user,
                                giver=referral_user,
                                db_record=user,
                                timestamp=time(),
                            )
                            referral_bonus.distribute()
                        except Exception as error:
                            print(error)
                            sentry.log_error(error)

        except Exception as e:
            sentry.log_error(e)
            pass
