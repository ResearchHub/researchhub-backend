from decimal import Decimal

from rest_framework import serializers

from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)


class UsdFundraiseContributionSerializer(serializers.ModelSerializer):
    """
    Expects the queryset to be annotated with `rsc_usd_rate_at_contribution`
    (the historical USD-per-RSC rate at the time of the contribution).
    """

    amount_usd = serializers.SerializerMethodField()
    amount_rsc = serializers.SerializerMethodField()
    fee_usd = serializers.SerializerMethodField()
    rsc_usd_rate = serializers.SerializerMethodField()

    class Meta:
        model = UsdFundraiseContribution
        fields = [
            "id",
            "fundraise",
            "amount_cents",
            "amount_usd",
            "amount_rsc",
            "fee_cents",
            "fee_usd",
            "rsc_usd_rate",
            "status",
            "created_date",
            "updated_date",
        ]
        read_only_fields = fields

    def _cents_to_usd(self, cents: int) -> str:
        return str((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))

    def get_amount_usd(self, obj: UsdFundraiseContribution) -> str:
        return self._cents_to_usd(obj.amount_cents)

    def get_fee_usd(self, obj: UsdFundraiseContribution) -> str:
        return self._cents_to_usd(obj.fee_cents)

    def get_rsc_usd_rate(self, obj: UsdFundraiseContribution) -> str | None:
        rate = obj.rsc_usd_rate_at_contribution
        return str(rate) if rate is not None else None

    def get_amount_rsc(self, obj: UsdFundraiseContribution) -> str | None:
        rate = obj.rsc_usd_rate_at_contribution
        if not rate:
            return None
        usd = Decimal(obj.amount_cents) / Decimal(100)
        rsc = usd / Decimal(str(rate))
        return str(rsc.quantize(Decimal("0.01")))
