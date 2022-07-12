from rest_framework import serializers

from discussion.serializers import (
    DynamicCommentSerializer,
    DynamicReplySerializer,
    DynamicThreadSerializer,
)
from reputation.models import Bounty
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_document.serializers import DynamicUnifiedDocumentSerializer
from user.serializers import DynamicUserSerializer


class BountySerializer(serializers.ModelSerializer):
    class Meta:
        model = Bounty
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicBountySerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    item = serializers.SerializerMethodField()
    solution = serializers.SerializerMethodField()

    class Meta:
        model = Bounty
        fields = "__all__"

    def get_created_by(self, bounty):
        context = self.context
        _context_fields = context.get("rep_dbs_get_created_by", {})
        serializer = DynamicUserSerializer(
            bounty.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_item(self, bounty):
        serializer = None
        context = self.context
        _context_fields = context.get("rep_dbs_get_item", {})
        model_name = bounty.item_content_type.model
        object_id = bounty.item_object_id
        model_class = bounty.item_content_type.model_class()
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

    def get_solution(self, bounty):
        serializer = None
        context = self.context
        _context_fields = context.get("rep_dbs_get_solution", {})
        solution_content_type = bounty.solution_content_type

        if not solution_content_type:
            return None

        model_name = solution_content_type.model
        object_id = bounty.solution_object_id
        model_class = bounty.solution_content_type.model_class()
        obj = model_class.objects.get(id=object_id)

        if model_name == "researchhubunifieddocument":
            serializer = DynamicUnifiedDocumentSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "thread":
            serializer = DynamicThreadSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "comment":
            serializer = DynamicCommentSerializer(
                obj, context=context, **_context_fields
            )
        elif model_name == "reply":
            serializer = DynamicReplySerializer(obj, context=context, **_context_fields)

        if serializer is not None:
            return serializer.data
        return None
