from rest_framework import serializers

from paper.related_models.paper_model import Paper
from purchase.related_models.payment_model import PaymentPurpose


class CheckoutSerializer(serializers.Serializer):
    success_url = serializers.URLField(required=True)
    failure_url = serializers.URLField(required=True)
    paper = serializers.PrimaryKeyRelatedField(
        queryset=Paper.objects.all(),
        required=False,
    )
    purpose = serializers.ChoiceField(
        choices=PaymentPurpose.choices,
        required=True,
    )

    def validate(self, attrs):
        purpose = attrs.get("purpose")
        paper = attrs.get("paper")

        if purpose == PaymentPurpose.APC and not paper:
            raise serializers.ValidationError(
                {"paper": "Paper is required when purpose is APC."}
            )

        return attrs
