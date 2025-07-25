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


class RscPurchaseCheckoutSerializer(serializers.Serializer):
    usd_amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=True,
        help_text="USD amount to purchase RSC",
    )
    success_url = serializers.URLField(
        required=True, help_text="URL to redirect to after successful payment"
    )
    cancel_url = serializers.URLField(
        required=True, help_text="URL to redirect to if payment is cancelled"
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

    def validate(self, attrs):
        # Calculate RSC amount and add to validated data
        usd_amount = attrs["usd_amount"]

        try:
            # Convert USD to RSC using the current exchange rate
            rsc_amount = RscExchangeRate.usd_to_rsc(float(usd_amount))

            # Store exchange rate for reference
            exchange_rate = RscExchangeRate.get_latest_exchange_rate()

            attrs["rsc_amount"] = Decimal(str(round(rsc_amount, 2)))
            attrs["exchange_rate"] = Decimal(str(exchange_rate))
        except Exception as e:
            raise serializers.ValidationError(
                f"Unable to calculate RSC amount: {str(e)}"
            )

        return attrs
