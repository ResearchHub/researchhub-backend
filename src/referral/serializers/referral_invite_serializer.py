from rest_framework.serializers import (
    ModelSerializer,
    SerializerMethodField,
    ValidationError,
)

from referral.models import ReferralInvite
from researchhub.settings import TESTING


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
            "recipient_email",
            "referral_first_name",
            "referral_last_name",
            "unified_document",
        ]

    def create(self, validated_data):
        data = validated_data
        instance = ReferralInvite.create(**data)

        if not TESTING:
            instance.send_invitation()

        return instance
