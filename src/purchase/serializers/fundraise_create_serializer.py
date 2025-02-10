from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from purchase.models import Fundraise
from purchase.related_models.constants.currency import USD
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.models import User


class FundraiseCreateSerializer(serializers.ModelSerializer):
    goal_amount = serializers.DecimalField(max_digits=19, decimal_places=2)
    goal_currency = serializers.CharField(default=USD)
    unified_document_id = serializers.IntegerField(required=False, allow_null=True)
    post_id = serializers.IntegerField(required=False, allow_null=True)
    recipient_user_id = serializers.IntegerField(required=True)

    class Meta:
        model = Fundraise
        fields = [
            "goal_amount",
            "goal_currency",
            "unified_document_id",
            "post_id",
            "recipient_user_id",
        ]

    def validate(self, data):
        # Validate required fields
        if not data.get("unified_document_id") and not data.get("post_id"):
            raise serializers.ValidationError(
                "Either unified_document_id or post_id is required"
            )

        # Validate goal amount
        try:
            goal_amount = Decimal(data["goal_amount"])
            if goal_amount <= 0:
                raise serializers.ValidationError("goal_amount must be greater than 0")
        except (TypeError, ValueError, InvalidOperation):
            raise serializers.ValidationError("Invalid goal_amount")

        # Validate currency
        if data["goal_currency"] != USD:
            raise serializers.ValidationError("goal_currency must be USD")

        # Get and validate unified document
        unified_document = None
        if data.get("unified_document_id"):
            try:
                unified_document = ResearchhubUnifiedDocument.objects.get(
                    id=data["unified_document_id"]
                )
            except ResearchhubUnifiedDocument.DoesNotExist:
                raise serializers.ValidationError("Unified document does not exist")
        elif data.get("post_id"):
            try:
                post = ResearchhubPost.objects.get(id=data["post_id"])
                unified_document = post.unified_document
            except ResearchhubPost.DoesNotExist:
                raise serializers.ValidationError("Post does not exist")

        # Validate document type
        if unified_document.document_type != PREREGISTRATION:
            raise serializers.ValidationError("Fundraise must be for a preregistration")

        # Check for existing fundraise
        existing_fundraise = Fundraise.objects.filter(
            unified_document=unified_document
        ).first()
        if existing_fundraise:
            raise serializers.ValidationError("Fundraise already exists")

        # Validate recipient user
        try:
            recipient_user = User.objects.get(id=data["recipient_user_id"])
        except User.DoesNotExist:
            raise serializers.ValidationError("Recipient user does not exist")

        # Add validated objects to data for use in create()
        data["unified_document"] = unified_document
        data["recipient_user"] = recipient_user

        return data
