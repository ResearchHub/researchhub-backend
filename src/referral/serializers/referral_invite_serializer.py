from rest_framework.serializers import (
    ModelSerializer,
    SerializerMethodField,
    ValidationError,
)

from referral.models import ReferralInvite


class ReferralInviteSerializer(ModelSerializer):
    class Meta:
        model = ReferralInvite
        fields = [
            "id",
            "inviter",
            "recipient",
            "recipient_email",
            "invite_type",
            "created_date",
        ]
