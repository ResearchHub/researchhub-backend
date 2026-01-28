from rest_framework import serializers


class PaymentIntentSerializer(serializers.Serializer):
    """
    Serializer for RSC purchase payment intent creation.
    """

    amount = serializers.DecimalField(
        max_digits=19,
        decimal_places=10,
        min_value=0.01,
        help_text="Amount of RSC to purchase",
    )

    def validate(self, attrs):
        amount = attrs.get("amount")

        # Ensure amount is positive
        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Amount must be greater than zero."}
            )

        return attrs
