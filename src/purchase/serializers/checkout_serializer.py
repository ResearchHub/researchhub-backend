from rest_framework import serializers

from purchase.related_models.payment_model import PaymentPurpose


class CheckoutSerializer(serializers.Serializer):
    success_url = serializers.URLField(required=True)
    failure_url = serializers.URLField(required=True)
    amount = serializers.IntegerField(
        min_value=1,
        help_text="Amount in cents.",
    )
    purpose = serializers.ChoiceField(
        choices=[
            (
                PaymentPurpose.RSC_PURCHASE.value,
                PaymentPurpose.RSC_PURCHASE.label,
            )
        ],
        required=True,
    )
