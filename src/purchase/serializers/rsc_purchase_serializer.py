from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from purchase.models import RscExchangeRate


class RscPurchasePreviewSerializer(serializers.Serializer):
    usd_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=True,
        help_text="USD amount to convert to RSC",
    )

    def validate_usd_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("USD amount must be greater than 0")

        # Minimum purchase amount of $1.00
        if value < Decimal("1.00"):
            raise serializers.ValidationError("Minimum purchase amount is $1.00")

        # Maximum purchase amount of $10,000.00 for security
        if value > Decimal("10000.00"):
            raise serializers.ValidationError("Maximum purchase amount is $10,000.00")

        return value
