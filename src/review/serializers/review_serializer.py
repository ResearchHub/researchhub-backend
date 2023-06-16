from rest_framework.serializers import ModelSerializer, SerializerMethodField

from researchhub.serializers import DynamicModelFieldSerializer
from review.models import Review


class ReviewSerializer(ModelSerializer):
    class Meta:
        model = Review
        fields = [
            "id",
            "score",
            "created_by",
            "unified_document",
            "is_removed",
            "object_id",
            "content_type",
        ]
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicReviewSerializer(
    DynamicModelFieldSerializer,
):
    created_by = SerializerMethodField()
    unified_document = SerializerMethodField()

    class Meta:
        model = Review
        fields = "__all__"

    def get_created_by(self, obj):
        from user.serializers import DynamicUserSerializer

        context = self.context
        _context_fields = context.get("rev_drs_get_created_by", {})
        serializer = DynamicUserSerializer(
            obj.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_unified_document(self, obj):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        context = self.context
        _context_fields = context.get("rev_drs_get_created_by", {})
        serializer = DynamicUnifiedDocumentSerializer(
            obj.unified_document, context=context, **_context_fields
        )
        return serializer.data
