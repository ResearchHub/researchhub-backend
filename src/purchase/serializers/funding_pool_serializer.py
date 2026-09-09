from rest_framework import serializers

from purchase.models import FundingPool
from purchase.related_models.constants.currency import RSC
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicUserSerializer


class FundingPoolContributionSerializer(serializers.Serializer):
    """Input validation for POST /api/funding_pool/{id}/create_contribution/."""

    amount = serializers.DecimalField(max_digits=19, decimal_places=10)
    amount_currency = serializers.ChoiceField(choices=[(RSC, RSC)], default=RSC)
    use_credits = serializers.BooleanField(default=True)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value


class FundingPoolDistributeSerializer(serializers.Serializer):
    """Input validation for POST /api/funding_pool/{id}/distribute/."""

    amount = serializers.DecimalField(max_digits=19, decimal_places=10)
    application_id = serializers.IntegerField()

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value


class DynamicFundingPoolSerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    amount_holding = serializers.SerializerMethodField()
    amount_distributed = serializers.SerializerMethodField()
    amount_raised = serializers.SerializerMethodField()

    class Meta:
        model = FundingPool
        fields = "__all__"

    def get_created_by(self, pool):
        context = self.context
        _context_fields = context.get("pch_dfps_get_created_by", {})
        serializer = DynamicUserSerializer(
            pool.created_by, context=context, **_context_fields
        )
        return serializer.data

    def _amount_currency_dict(self, rsc_amount):
        try:
            usd_amount = RscExchangeRate.rsc_to_usd(float(rsc_amount))
        except AttributeError:
            usd_amount = None
        return {
            "rsc": rsc_amount,
            "usd": usd_amount,
        }

    def get_amount_holding(self, pool):
        return self._amount_currency_dict(pool.amount_holding)

    def get_amount_distributed(self, pool):
        return self._amount_currency_dict(pool.amount_distributed)

    def get_amount_raised(self, pool):
        return self._amount_currency_dict(pool.amount_raised)
