from rest_framework.serializers import ModelSerializer, SerializerMethodField

from hypothesis.models import Hypothesis
from paper.models import Paper
from paper.serializers import DynamicPaperSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.models import RhCommentThreadModel
from researchhub_comment.serializers.constants.rh_comment_thread_serializer_constants import (
    RH_COMMENT_THREAD_FIELDS,
    RH_COMMENT_THREAD_READ_ONLY_FIELDS,
)
from researchhub_document.models import ResearchhubPost
from researchhub_document.serializers import DynamicPostSerializer


class RhCommentThreadSerializer(ModelSerializer):
    comments = SerializerMethodField()

    class Meta:
        model = RhCommentThreadModel
        fields = RH_COMMENT_THREAD_FIELDS
        read_only_fields = RH_COMMENT_THREAD_READ_ONLY_FIELDS

    def get_comments(self, thread):
        from researchhub_comment.serializers import RhCommentSerializer

        return RhCommentSerializer(
            # Only need to fetch top-level comments. Responses are nested comments
            thread.rh_comments.filter(parent__id=None),
            many=True,
        ).data


class DynamicRhThreadSerializer(DynamicModelFieldSerializer):
    comments = SerializerMethodField()
    content_object = SerializerMethodField()

    class Meta:
        fields = "__all__"
        model = RhCommentThreadModel

    def get_comments(self, thread):
        from researchhub_comment.serializers import DynamicRhCommentSerializer

        context = self.context
        _context_fields = context.get("rhc_dts_get_comments", {})
        _filter_fields = _context_fields.get("_filter_fields", {})
        serializer = DynamicRhCommentSerializer(
            thread.rh_comments.filter(**_filter_fields),
            many=True,
            context=context,
            **_context_fields,
        )
        return serializer.data

    def get_content_object(self, thread):
        context = self.context
        _context_fields = context.get("rhc_dts_get_content_object", {})
        content_object = thread.content_object

        serializer = None
        if isinstance(content_object, Paper):
            serializer = DynamicPaperSerializer
        elif isinstance(content_object, ResearchhubPost):
            serializer = DynamicPostSerializer
        elif isinstance(content_object, Hypothesis):
            from hypothesis.serializers import DynamicHypothesisSerializer

            serializer = DynamicHypothesisSerializer

        if not serializer:
            raise Exception(f"No content object serializer for {str(content_object)}")

        serializer_data = serializer(
            content_object, context=context, **_context_fields
        ).data
        return serializer_data
