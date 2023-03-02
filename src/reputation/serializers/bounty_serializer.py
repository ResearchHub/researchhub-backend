from rest_framework import serializers

from discussion.serializers import (
    DynamicCommentSerializer,
    DynamicReplySerializer,
    DynamicThreadSerializer,
)
from reputation.models import Bounty, BountySolution
from reputation.serializers.escrow_serializer import DynamicEscrowSerializer
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


class BountySolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BountySolution
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicBountySerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    escrow = serializers.SerializerMethodField()
    item = serializers.SerializerMethodField()
    solutions = serializers.SerializerMethodField()

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

    def get_content_type(self, bounty):
        content_type = bounty.item_content_type
        return {"id": content_type.id, "name": content_type.model}

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

    def get_escrow(self, bounty):
        context = self.context
        _context_fields = context.get("rep_dbs_get_escrow", {})
        serializer = DynamicEscrowSerializer(
            bounty.escrow, context=context, **_context_fields
        )
        return serializer.data

    def get_solutions(self, bounty):
        serializer = None
        context = self.context
        _context_fields = context.get("rep_dbs_get_solutions", {})
        serializer = DynamicBountySolutionSerializer(
            bounty.solutions, context=context, many=True, **_context_fields
        )
        return serializer.data


class DynamicBountySolutionSerializer(DynamicModelFieldSerializer):
    bounty = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    item = serializers.SerializerMethodField()

    class Meta:
        model = BountySolution
        fields = "__all__"

    def get_bounty(self, solution):
        context = self.context
        _context_fields = context.get("rep_dbss_get_bounty", {})
        serializer = DynamicBountySerializer(
            solution.bounty, context=context, **_context_fields
        )
        return serializer.data

    def get_content_type(self, solution):
        content_type = solution.content_type
        return {"id": content_type.id, "name": content_type.model}

    def get_item(self, solution):
        context = self.context
        _context_fields = context.get("rep_dbss_get_item", {})

        solution_content_type = solution.content_type
        model_name = solution_content_type.model
        object_id = solution.object_id
        model_class = solution_content_type.model_class()
        obj = model_class.objects.get(id=object_id)

        if model_name == "thread":
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
