from rest_framework import serializers

from purchase.related_models.fundraise_model import Fundraise


class PaymentIntentSerializer(serializers.Serializer):
    """
    Serializer for RSC purchase payment intent creation.

    Optionally accepts a fundraise_id to automatically contribute
    the purchased RSC to a fundraise once the payment is processed.
    """

    amount = serializers.DecimalField(
        max_digits=19,
        decimal_places=10,
        min_value=0.01,
        help_text="Amount of RSC to purchase",
    )
    fundraise_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional fundraise ID to auto-contribute to after purchase",
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

    def validate(self, attrs):
        amount = attrs.get("amount")

        # Ensure amount is positive
        if amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Amount must be greater than zero."}
            )

        return attrs
