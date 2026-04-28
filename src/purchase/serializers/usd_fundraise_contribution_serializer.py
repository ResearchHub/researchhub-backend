from decimal import Decimal

from rest_framework import serializers

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)


class UsdFundraiseContributionSerializer(serializers.ModelSerializer):
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

    def _cents_to_usd(self, cents):
        return str((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))

    def _historical_rate(self, obj):
        exchange_rate = (
            RscExchangeRate.objects.filter(created_date__lte=obj.created_date)
            .order_by("created_date")
            .last()
        )
        if exchange_rate is None:
            return None
        return exchange_rate.real_rate or exchange_rate.rate

    def get_amount_usd(self, obj):
        return self._cents_to_usd(obj.amount_cents)

    def get_fee_usd(self, obj):
        return self._cents_to_usd(obj.fee_cents)

    def get_rsc_usd_rate(self, obj):
        rate = self._historical_rate(obj)
        return str(rate) if rate is not None else None

    def get_amount_rsc(self, obj):
        rate = self._historical_rate(obj)
        if not rate:
            return None
        usd = Decimal(obj.amount_cents) / Decimal(100)
        rsc = usd / Decimal(str(rate))
        return str(rsc.quantize(Decimal("0.01")))
