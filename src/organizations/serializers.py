from rest_framework import serializers

from organizations.models import NonprofitFundraiseLink, NonprofitOrg


class NonprofitOrgSerializer(serializers.ModelSerializer):
    """Serializer for the NonprofitOrg model."""

    class Meta:
        model = NonprofitOrg
        fields = [
            "id",
            "name",
            "ein",
            "endaoment_org_id",
            "base_wallet_address",
            "created_date",
            "updated_date",
        ]
        read_only_fields = ["id", "created_date", "updated_date"]


class NonprofitFundraiseLinkSerializer(serializers.ModelSerializer):
    """Serializer for the NonprofitFundraiseLink model."""

    class Meta:
        model = NonprofitFundraiseLink
        fields = [
            "id",
            "nonprofit",
            "fundraise",
            "note",
            "created_date",
            "updated_date",
        ]
        read_only_fields = ["id", "created_date", "updated_date"]
