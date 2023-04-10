from rest_framework import serializers

from discussion.serializers import DynamicThreadSerializer
from reputation.models import Escrow
from reputation.serializers.bounty_fee_serializer import DynamicBountyFeeSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.serializers import DynamicUserSerializer


class EscrowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Escrow
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicEscrowSerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    recipients = serializers.SerializerMethodField()
    item = serializers.SerializerMethodField()
    bounty_fee = serializers.SerializerMethodField()

    class Meta:
        model = Escrow
        fields = "__all__"

    def get_created_by(self, escrow):
        context = self.context
        _context_fields = context.get("rep_des_get_created_by", {})
        serializer = DynamicUserSerializer(
            escrow.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_recipients(self, escrow):
        context = self.context
        _context_fields = context.get("rep_des_get_recipients", {})
        serializer = DynamicUserSerializer(
            escrow.recipients, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_item(self, escrow):
        serializer = None
        context = self.context
        _context_fields = context.get("rep_des_get_item", {})
        model_name = escrow.content_type.model
        object_id = escrow.object_id
        model_class = escrow.content_type.model_class()
        obj = model_class.objects.get(id=object_id)

        if model_name == "researchhubunifieddocument":
            serializer = DynamicUnifiedDocumentSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "thread":
            serializer = DynamicThreadSerializer(
                obj, context=context, **_context_fields
            )

        if serializer is not None:
            return serializer.data
        return None

    def get_bounty_fee(self, escrow):
        context = self.context
        _context_fields = context.get("rep_des_get_bounty_fee", {})
        serializer = DynamicBountyFeeSerializer(
            escrow.bounty_fee, context=context, **_context_fields
        )
        return serializer.data
