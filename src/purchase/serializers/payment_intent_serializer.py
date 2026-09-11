from rest_framework import serializers

from purchase.related_models.constants import MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC
from purchase.related_models.funding_pool_model import FundingPool
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.payment_model import (
    PAYMENT_INTENT_PURPOSES,
    PaymentPurpose,
)


class PaymentIntentSerializer(serializers.Serializer):
    """
    Serializer for RSC purchase payment intent creation.

    Optionally accepts a fundraise_id or funding_pool_id (mutually exclusive)
    to automatically contribute the purchased RSC once the payment is processed.
    A FUNDING_CREDITS_PURCHASE purpose only tops up the user's funding credits,
    so it cannot carry a contribution target.
    """

    amount = serializers.DecimalField(
        max_digits=19,
        decimal_places=10,
        min_value=MINIMUM_FUNDRAISE_CONTRIBUTION_AMOUNT_RSC,
        help_text="Amount of RSC to purchase",
    )
    purpose = serializers.ChoiceField(
        choices=[(purpose.value, purpose.label) for purpose in PAYMENT_INTENT_PURPOSES],
        default=PaymentPurpose.RSC_PURCHASE,
        help_text="RSC_PURCHASE (optionally auto-contributed) or "
        "FUNDING_CREDITS_PURCHASE (credits only)",
    )
    fundraise_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional fundraise ID to auto-contribute to after purchase",
    )
    funding_pool_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional funding pool ID to auto-contribute to after purchase",
    )

    def validate_fundraise_id(self, value):
        if value is None:
            return value

        try:
            fundraise = Fundraise.objects.get(id=value)
        except Fundraise.DoesNotExist:
            raise serializers.ValidationError("Fundraise not found.")

        if fundraise.status != Fundraise.OPEN:
            raise serializers.ValidationError(
                "Fundraise is not open for contributions."
            )

        if fundraise.is_expired():
            raise serializers.ValidationError("Fundraise has expired.")

        return value

    def validate_funding_pool_id(self, value):
        if value is None:
            return value

        try:
            pool = FundingPool.objects.get(id=value)
        except FundingPool.DoesNotExist:
            raise serializers.ValidationError("Funding pool not found.")

        if not pool.is_valid_for_contribution:
            raise serializers.ValidationError(
                "Funding pool is not open for contributions."
            )

        return value

    def validate(self, attrs):
        amount = attrs.get("amount")

        # Ensure amount is positive
        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Amount must be greater than zero."}
            )

        fundraise_id = attrs.get("fundraise_id")
        funding_pool_id = attrs.get("funding_pool_id")
        if fundraise_id is not None and funding_pool_id is not None:
            raise serializers.ValidationError(
                "fundraise_id and funding_pool_id are mutually exclusive."
            )

        has_target = fundraise_id is not None or funding_pool_id is not None
        if (
            attrs.get("purpose") == PaymentPurpose.FUNDING_CREDITS_PURCHASE
            and has_target
        ):
            raise serializers.ValidationError(
                "A funding credits purchase cannot target a fundraise or funding pool."
            )

        return attrs
