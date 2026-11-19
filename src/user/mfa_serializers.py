from dj_rest_auth.mfa.serializers import TOTPActivateConfirmSerializer
from dj_rest_auth.mfa.totp import TOTP
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


class PasswordConfirmedTOTPActivateSerializer(TOTPActivateConfirmSerializer):
    password = serializers.CharField(
        required=False, write_only=True, trim_whitespace=False
    )

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.has_usable_password():
            raise serializers.ValidationError(
                {
                    "password": [
                        _(
                            "Set a password using the password reset email before "
                            "enabling two-factor authentication."
                        )
                    ]
                }
            )
        if not user.check_password(attrs.get("password", "")):
            raise serializers.ValidationError(
                {
                    "password": [
                        _(
                            "Enter your current password to enable two-factor "
                            "authentication."
                        )
                    ]
                }
            )
        return super().validate(attrs)


class TOTPCodeConfirmationSerializer(serializers.Serializer):
    code = serializers.CharField()

    def validate_code(self, code):
        if not TOTP.validate_code(self.context["request"].user, code):
            raise serializers.ValidationError(_("Invalid code."))
        return code
