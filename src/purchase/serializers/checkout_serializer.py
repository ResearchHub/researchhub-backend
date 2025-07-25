from decimal import Decimal

from rest_framework import serializers

import paper
from purchase.models import RscExchangeRate


class CheckoutSerializer(serializers.Serializer):
    success_url = serializers.URLField(required=True)
    failure_url = serializers.URLField(required=True)

    # Paper-specific fields
    paper = serializers.PrimaryKeyRelatedField(
        queryset=paper.models.Paper.objects.all(),
        required=False,
    )

    # RSC purchase-specific fields
    purchase_type = serializers.ChoiceField(
        choices=["paper_apc", "rsc_purchase"],
        default="paper_apc",
        required=False,
    )
    usd_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="USD amount for RSC purchase",
    )

    def validate(self, attrs):
        purchase_type = attrs.get("purchase_type", "paper_apc")

        if purchase_type == "paper_apc":
            if not attrs.get("paper"):
                raise serializers.ValidationError(
                    "Paper is required for APC fee payments"
                )
        elif purchase_type == "rsc_purchase":
            if not attrs.get("usd_amount"):
                raise serializers.ValidationError(
                    "USD amount is required for RSC purchases"
                )

            # Validate USD amount
            usd_amount = attrs["usd_amount"]
            if usd_amount <= 0:
                raise serializers.ValidationError("USD amount must be greater than 0")

            # Calculate RSC amount
            try:
                rsc_amount = RscExchangeRate.usd_to_rsc(float(usd_amount))
                exchange_rate = RscExchangeRate.get_latest_exchange_rate()

                attrs["rsc_amount"] = Decimal(str(round(rsc_amount, 2)))
                attrs["exchange_rate"] = Decimal(str(exchange_rate))
            except Exception as e:
                raise serializers.ValidationError(
                    f"Unable to calculate RSC amount: {str(e)}"
                )

        return attrs
