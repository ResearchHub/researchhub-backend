from allauth.account import app_settings
from allauth.utils import get_user_model
from django.http import HttpRequest
from django.urls.exceptions import NoReverseMatch
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from oauth.exceptions import LoginError
from oauth.helpers import complete_social_login
from user.models import User
from utils import sentry


class SocialLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=True, allow_blank=True)
    referral_code = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    def _get_request(self):
        request = self.context.get("request")
        if not isinstance(request, HttpRequest):
            request = request._request
        return request

    def validate(self, attrs):
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

        access_token = attrs.get("access_token")

        social_token = adapter.parse_token({"access_token": access_token})
        social_token.app = app
        social_token.token = access_token

        login = self.handle_social_login(adapter, app, social_token)
        self.check_duplicates_then_save_social_login(request, login)

        login_user = login.account.user
        attrs["user"] = login_user
        self.handle_referral(attrs)
        return attrs

    def handle_social_login(
        self,
        adapter,
        app,
        social_token,
    ):
        """
        :param adapter: allauth.socialaccount Adapter subclass.
            Usually OAuthAdapter or Auth2Adapter
        :param app: `allauth.socialaccount.SocialApp` instance
        :param social_token: `allauth.socialaccount.SocialToken` instance
        :returns: A populated instance of the
            `allauth.socialaccount.SocialLoginView` instance
        """
        try:
            request = self._get_request()
            social_login = adapter.complete_login(
                # NOTE: argument order matters here.
                request,
                app,
                social_token,
            )
            complete_social_login(request, social_login)
        except NoReverseMatch as e:
            if "account_inactive" in str(e):
                raise LoginError(None, "Account is suspended")
        except Exception as e:
            sentry.log_error(e, message="Social login failed")
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
                    raise serializers.ValidationError(
                        _("User already registered with this email address.")
                    )

            login.lookup()
            login.save(request, connect=True)

    def handle_referral(self, attrs):
        try:
            referral_code = attrs.get("referral_code")
            if referral_code and referral_code.strip():
                referral_user = User.objects.get(referral_code=referral_code.strip())
                user = attrs["user"]

                invited_by_flag_not_set = (
                    referral_code
                    and not user.invited_by
                    and referral_user.id != user.id
                )
                if invited_by_flag_not_set:
                    user.invited_by = referral_user
                    user.save()
        except Exception as e:
            sentry.log_error(e)
            pass
