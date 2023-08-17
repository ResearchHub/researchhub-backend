from django.contrib.contenttypes.models import ContentType
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from citation.models import CitationEntry
from hypothesis.models import Hypothesis
from paper.models import Paper
from paper.serializers import DynamicPaperSerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_access_group.constants import PRIVATE, PUBLIC, WORKSPACE
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
    comment_count = SerializerMethodField()
    content_object = SerializerMethodField()
    privacy_type = SerializerMethodField()
    related_content = SerializerMethodField()

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

    def get_related_content(self, thread):
        content_object = thread.content_object

        content_type = ContentType.objects.get_for_model(content_object)
        model_name = content_type.model

        return {
            "id": content_object.id,
            "content_type": model_name,
        }

    def get_comment_count(self, thread):
        return thread.rh_comments.count()

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
        elif isinstance(content_object, CitationEntry):
            from citation.serializers import DynamicCitationEntrySerializer

            serializer = DynamicCitationEntrySerializer

        if not serializer:
            raise Exception(f"No content object serializer for {str(content_object)}")

        serializer_data = serializer(
            content_object, context=context, **_context_fields
        ).data
        serializer_data["name"] = content_object._meta.model_name
        return serializer_data

    def get_privacy_type(self, thread):
        permissions = thread.permissions
        if permissions.exists():
            permission = permissions.first()
            if permission.organization:
                return WORKSPACE
            else:
                return PRIVATE
        return PUBLIC
