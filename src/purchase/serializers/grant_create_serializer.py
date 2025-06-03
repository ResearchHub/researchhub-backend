from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from purchase.models import Grant
from purchase.related_models.constants.currency import USD
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument


class GrantCreateSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=19, decimal_places=2)
    currency = serializers.CharField(default=USD)
    organization = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    description = serializers.CharField()
    unified_document_id = serializers.IntegerField(required=False, allow_null=True)
    post_id = serializers.IntegerField(required=False, allow_null=True)
    end_date = serializers.DateTimeField(required=False, allow_null=True)
    contact_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        help_text="List of user IDs to set as contacts for this grant",
    )

    class Meta:
        model = Grant
        fields = [
            "amount",
            "currency",
            "organization",
            "description",
            "unified_document_id",
            "post_id",
            "end_date",
            "contact_ids",
        ]

    def validate(self, data):
        # Validate required fields
        if not data.get("unified_document_id") and not data.get("post_id"):
            raise serializers.ValidationError(
                "Either unified_document_id or post_id is required"
            )

        # Validate grant amount
        try:
            amount = Decimal(data["amount"])
            if amount <= 0:
                raise serializers.ValidationError("amount must be greater than 0")
        except (TypeError, ValueError, InvalidOperation):
            raise serializers.ValidationError("Invalid amount")

        # Validate currency
        if data["currency"] != USD:
            raise serializers.ValidationError("currency must be USD")

        # Validate contacts if provided
        contact_ids = data.get("contact_ids", [])
        if contact_ids:
            from user.models import User

            valid_contacts = User.objects.filter(id__in=contact_ids)
            if len(valid_contacts) != len(contact_ids):
                raise serializers.ValidationError(
                    "One or more contact users do not exist"
                )

        # Validate description
        description = data.get("description", "").strip()
        if not description:
            raise serializers.ValidationError("description is required")

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

        # Add validated objects to data for use in create()
        data["unified_document"] = unified_document

        return data

    def create(self, validated_data):
        contact_ids = validated_data.pop("contact_ids", [])
        grant = super().create(validated_data)

        if contact_ids:
            from user.models import User

            contacts = User.objects.filter(id__in=contact_ids)
            grant.contacts.set(contacts)

        return grant
