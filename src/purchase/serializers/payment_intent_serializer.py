from rest_framework import serializers

from purchase.related_models.constants.currency import RSC, USD


class PaymentIntentSerializer(serializers.Serializer):
    """
    Serializer for RSC purchase payment intent creation.
    """

    amount = serializers.IntegerField(
        min_value=1,  # Minimum $0.01 for USD, or minimum RSC amount
        help_text="Amount in cents (USD) or RSC units (if currency is RSC)",
    )
    currency = serializers.ChoiceField(
        choices=[(USD, "USD"), (RSC, "RSC")],
        default=USD,
        help_text="Currency for the amount (USD or RSC)",
    )

    def validate(self, attrs):
        amount = attrs.get("amount")
        currency = attrs.get("currency", USD)

        # Ensure amount is positive
        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Amount must be greater than zero."}
            )

        # Ensure currency is valid
        if currency not in [USD, RSC]:
            raise serializers.ValidationError(
                {"currency": "Currency must be either 'USD' or 'RSC'."}
            )

        return attrs
