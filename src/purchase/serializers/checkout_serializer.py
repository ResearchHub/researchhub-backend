from rest_framework import serializers

from paper.related_models.paper_model import Paper
from purchase.related_models.payment_model import PaymentPurpose


class CheckoutSerializer(serializers.Serializer):
    success_url = serializers.URLField(required=True)
    failure_url = serializers.URLField(required=True)
    amount = serializers.IntegerField(
        min_value=1,
        help_text="Amount in cents.",
        required=False,
    )
    paper = serializers.PrimaryKeyRelatedField(
        queryset=Paper.objects.all(),
        required=False,
    )
    purpose = serializers.ChoiceField(
        choices=PaymentPurpose.choices,
        required=True,
    )

    def validate(self, attrs):
        amount = attrs.get("amount")
        paper = attrs.get("paper")
        purpose = attrs.get("purpose")

        if purpose == PaymentPurpose.APC and not paper:
            raise serializers.ValidationError(
                {"paper": "Paper is required when purpose is APC."}
            )

        if purpose != PaymentPurpose.APC and amount <= 0:
            raise serializers.ValidationError(
                {"amount": "Amount must be greater than zero."}
            )

        return attrs
