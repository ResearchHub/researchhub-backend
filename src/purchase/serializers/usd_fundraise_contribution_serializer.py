from decimal import Decimal

from rest_framework import serializers

from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)


class UsdFundraiseContributionSerializer(serializers.ModelSerializer):
    amount_usd = serializers.SerializerMethodField()
    fee_usd = serializers.SerializerMethodField()

    class Meta:
        model = UsdFundraiseContribution
        fields = [
            "id",
            "fundraise",
            "amount_cents",
            "amount_usd",
            "fee_cents",
            "fee_usd",
            "status",
            "created_date",
            "updated_date",
        ]
        read_only_fields = fields

    def _cents_to_usd(self, cents):
        return str((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))

    def get_amount_usd(self, obj):
        return self._cents_to_usd(obj.amount_cents)

    def get_fee_usd(self, obj):
        return self._cents_to_usd(obj.fee_cents)
