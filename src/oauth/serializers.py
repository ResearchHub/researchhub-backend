import logging
from typing import Any

from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error
from dj_rest_auth.registration.serializers import (
    SocialLoginSerializer as BaseSocialLoginSerializer,
)
from django.conf import settings
from django.urls.exceptions import NoReverseMatch
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from oauth.adapters import XOAuth2Adapter
from user.models import User

logger = logging.getLogger(__name__)


class SocialLoginSerializer(BaseSocialLoginSerializer):
    referral_code = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except NoReverseMatch as e:
            if "account_inactive" in str(e):
                raise serializers.ValidationError(_("Account is suspended"))
            raise
        except serializers.ValidationError:
            raise
        except Exception as e:
            logger.error("Social login failed", exc_info=e)
            raise serializers.ValidationError(_("Incorrect value"))

    def post_signup(self, login, attrs):
        """Handle referral code after signup."""
        self._handle_referral(login.account.user, attrs)

    def _handle_referral(self, user, attrs):
        try:
            referral_code = attrs.get("referral_code")
            if referral_code and referral_code.strip():
                referral_user = User.objects.get(referral_code=referral_code.strip())
                if not user.invited_by and referral_user.id != user.id:
                    user.invited_by = referral_user
                    user.save()
        except Exception as e:
            logger.error(
                f"Failed to handle referral code for user {user.id}", exc_info=e
            )


class XLoginSerializer(SocialLoginSerializer):
    access_token = None
    id_token = None
    code = serializers.CharField(trim_whitespace=False)
    code_verifier = serializers.CharField(
        min_length=43, max_length=128, trim_whitespace=False
    )
    redirect_uri = serializers.URLField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Exchange an X authorization code for this application's access token."""
        attrs.pop("redirect_uri", None)
        request = self._get_request()
        adapter = XOAuth2Adapter(request)
        app = adapter.get_provider().app
        client = OAuth2Client(
            request,
            app.client_id,
            app.secret,
            adapter.access_token_method,
            adapter.access_token_url,
            settings.X_REDIRECT_URI,
            basic_auth=adapter.basic_auth,
        )
        try:
            tokens = client.get_access_token(
                attrs.pop("code"), pkce_code_verifier=attrs.pop("code_verifier")
            )
        except OAuth2Error as exc:
            raise serializers.ValidationError(
                {"code": "Failed to exchange X authorization code."}
            ) from exc
        attrs["access_token"] = tokens["access_token"]
        return super().validate(attrs)
