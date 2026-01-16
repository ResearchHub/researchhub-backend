import logging

from dj_rest_auth.registration.serializers import (
    SocialLoginSerializer as BaseSocialLoginSerializer,
)
from django.urls.exceptions import NoReverseMatch
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

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
