from itertools import chain

from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny

from discussion.reaction_serializers import DynamicVoteSerializer
from hub.serializers import DynamicHubSerializer
from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty
from reputation.serializers.bounty_serializer import DynamicBountySerializer
from researchhub.serializers import DynamicModelFieldSerializer
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.serializers.rh_comment_serializer import (
    DynamicRhCommentSerializer,
)
from user.models import Action
from user.serializers import DynamicUserSerializer
from utils.http import get_user_from_request


class DynamicFeedSerializer(DynamicModelFieldSerializer):
    item = serializers.SerializerMethodField()
    hubs = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    unified_document = serializers.SerializerMethodField()
    user_vote = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = "__all__"

    def get_unified_document(self, obj):
        from researchhub_document.serializers import DynamicUnifiedDocumentSerializer

        if obj.unified_document is None:
            return None

        context = self.context
        _context_fields = context.get("feed_get_unified_document", {})
        serializer = DynamicUnifiedDocumentSerializer(
            obj.unified_document, context=context, **_context_fields
        )
        return serializer.data

    def get_score(self, obj):
        if obj._meta.model_name == "paper":
            return obj.unified_document.score
        elif obj._meta.model_name == "rhcommentmodel":
            return obj.score
        elif obj._meta.model_name == "bounty":
            return obj.item.score

        return None

    def get_hubs(self, obj):
        unified_document = obj.unified_document

        if unified_document is None or unified_document.hubs is None:
            return []

        context = self.context
        _context_fields = context.get("feed_get_hubs", {})
        serializer = DynamicHubSerializer(
            unified_document.hubs, many=True, context=context, **_context_fields
        )
        return serializer.data

    def get_user_vote(self, obj):
        user = get_user_from_request(self.context)
        if user and not user.is_anonymous:
            vote = obj.votes.filter(created_by_id=user)
            if vote.exists():
                return DynamicVoteSerializer(vote).data

        return None

    def get_created_by(self, obj):
        if obj._meta.model_name == "paper":
            return None

        elif obj._meta.model_name == "rhcommentmodel":
            context = self.context
            _context_fields = context.get("rhc_dcs_get_created_by", {})
            serializer = DynamicUserSerializer(
                obj.created_by, context=context, **_context_fields
            )
            return serializer.data
        elif obj._meta.model_name == "bounty":
            context = self.context
            _context_fields = context.get("rhc_dcs_get_created_by", {})
            serializer = DynamicUserSerializer(
                obj.created_by, context=context, **_context_fields
            )
            return serializer.data

        return None

    def get_item(self, obj):
        from paper.serializers import DynamicPaperSerializer

        serializer = None
        context = self.context

        if obj._meta.model_name == "paper":
            _context_fields = context.get("feed_get_paper_item", {})
            serializer = DynamicPaperSerializer(obj, context=context, **_context_fields)
        elif obj._meta.model_name == "rhcommentmodel":
            _context_fields = context.get("feed_get_comment_item", {})
            serializer = DynamicRhCommentSerializer(
                obj, context=context, **_context_fields
            )
        elif obj._meta.model_name == "bounty":
            _context_fields = context.get("feed_get_bounty_item", {})
            serializer = DynamicBountySerializer(
                obj, context=context, **_context_fields
            )

        if serializer is not None:
            return serializer.data

        return None

    def get_content_type(self, obj):
        if obj._meta.model_name == "paper":
            return "paper"
        elif obj._meta.model_name == "rhcommentmodel":
            return "comment"
        elif obj._meta.model_name == "bounty":
            return "bounty"

        return "unknown"


class FeedViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Action.objects.all()
    permission_classes = [AllowAny]

    def _get_feed_context(self):
        context = {
            "feed_get_paper_item": {
                "_include_fields": [
                    "id",
                    "created_date",
                    "updated_date",
                    "unified_document",
                    "abstract",
                    "raw_authors",
                ]
            },
            "feed_get_bounty_item": {
                "_include_fields": [
                    "id",
                    "amount",
                    "status",
                    "expiration_date",
                    "bounty_type",
                    "item",
                    "created_by",
                    "created_date",
                    "updated_date",
                ]
            },
            "feed_get_comment_item": {
                "_include_fields": [
                    "id",
                    "created_date",
                    "updated_date",
                    "created_by",
                    "comment_content_json",
                ]
            },
            "rep_dbs_get_item": {
                "_include_fields": [
                    "id",
                    "created_date",
                    "updated_date",
                    "created_by",
                    "comment_content_json",
                ]
            },
            "rhc_dcs_get_parent": {
                "_include_fields": [
                    "id",
                    "created_date",
                    "updated_date",
                    "created_by",
                    "comment_content_json",
                ]
            },
            "feed_get_hubs": {"_include_fields": ["id", "slug", "name"]},
            "feed_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                    "editor_of",
                ]
            },
            "rep_dbs_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                    "editor_of",
                ]
            },
            "feed_get_unified_document": {"_include_fields": ["id", "documents"]},
            "doc_duds_get_documents": {
                "_include_fields": [
                    "id",
                    "slug",
                    "title",
                ]
            },
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "slug",
                    "documents",
                ]
            },
            "rhc_dcs_get_created_by": {
                "_include_fields": (
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                    "editor_of",
                )
            },
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
                    "is_verified",
                )
            },
        }

        return context

    def list(self, request, *args, **kwargs):
        rec_ids = ["comment_60", "paper_6", "bounty_9", "bounty_12"]
        analytics_ids = [item_id.split("_") for item_id in rec_ids if "_" in item_id]
        paper_ids = [
            analytics_id[1]
            for analytics_id in analytics_ids
            if analytics_id[0] == "paper"
        ]
        comment_ids = [
            analytics_id[1]
            for analytics_id in analytics_ids
            if analytics_id[0] == "comment"
        ]
        bounty_ids = [
            analytics_id[1]
            for analytics_id in analytics_ids
            if analytics_id[0] == "bounty"
        ]

        papers = Paper.objects.filter(id__in=paper_ids)
        comments = RhCommentModel.objects.filter(id__in=comment_ids)
        bounties = Bounty.objects.filter(id__in=bounty_ids)
        combined_queryset = list(chain(bounties, comments, papers))

        page = self.paginate_queryset(combined_queryset)

        serializer = DynamicFeedSerializer(
            page,
            many=True,
            context=self._get_feed_context(),
            _include_fields=[
                "created_by",
                "created_date",
                "content_type",
                "hubs",
                "item",
                "score",
                "user_vote",
                "unified_document",
            ],
        )
        data = serializer.data
        return self.get_paginated_response(data)
