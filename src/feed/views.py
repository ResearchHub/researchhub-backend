import random
from datetime import datetime, timedelta
from itertools import chain

import boto3
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

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
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from researchhub_document.serializers.researchhub_post_serializer import (
    DynamicPostSerializer,
)
from user.models import Action
from user.serializers import DynamicUserSerializer
from utils import sentry
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
        elif obj._meta.model_name == "researchhubpost":
            return obj.score

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
        elif obj._meta.model_name == "researchhubpost":
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
        elif obj._meta.model_name == "researchhubpost":
            _context_fields = context.get("feed_get_post_item", {})
            serializer = DynamicPostSerializer(obj, context=context, **_context_fields)

        if serializer is not None:
            return serializer.data

        return None

    def get_content_type(self, obj):
        try:
            if obj._meta.model_name == "paper":
                return "paper"
            elif obj._meta.model_name == "rhcommentmodel":
                return "comment"
            elif obj._meta.model_name == "bounty":
                return "bounty"
            elif obj._meta.model_name == "researchhubpost":
                return obj.unified_document.get_client_doc_type()
        except Exception as e:
            sentry.log_info("Could not resolve feed content_type", error=e)

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
                    # "unified_document",
                    "abstract",
                    "raw_authors",
                ]
            },
            "feed_get_post_item": {
                "_include_fields": [
                    "id",
                    "created_date",
                    "updated_date",
                    # "unified_document",
                    "renderable_text",
                    "authors",
                    "created_by",
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
                    "parent",
                    "created_by",
                    "created_date",
                    "updated_date",
                ]
            },
            "rep_dbs_get_item": {
                "_include_fields": [
                    "id",
                    "amount",
                    "status",
                    "expiration_date",
                    "bounty_type",
                    "parent",
                    "created_by",
                    "created_date",
                    "updated_date",
                    "comment_content_json",
                ]
            },
            "rep_dbs_get_parent": {
                "_include_fields": [
                    "id",
                    "amount",
                    "status",
                    "expiration_date",
                    "bounty_type",
                    "item",
                    "parent",
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
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                ]
            },
            "doc_dps_get_authors": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "created_date",
                    "is_verified",
                ]
            },
            "feed_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
                ]
            },
            "rep_dbs_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                    "first_name",
                    "last_name",
                    "is_verified",
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
            "doc_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "slug",
                    "documents",
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
                )
            },
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "profile_image",
                    "is_verified",
                )
            },
        }

        return context

    def _get_ranked_recent_object_ids(self, user_id):
        personalize_runtime = boto3.client(
            "personalize-runtime", region_name="us-west-2"
        )
        user_ranking_campaign_arn = (
            "arn:aws:personalize:us-west-2:794128250202:campaign/hp-re-ranking"
        )

        open_bounties = Bounty.objects.filter(
            status="OPEN",
            expiration_date__gte=datetime.now(),
        ).order_by("expiration_date")[:400]
        open_bounty_ids = [f"bounty_{bounty.id}" for bounty in open_bounties]

        response = personalize_runtime.get_personalized_ranking(
            campaignArn=user_ranking_campaign_arn,
            inputList=open_bounty_ids,
            userId=user_id,
        )
        ranked_bounty_ids = [item["itemId"] for item in response["personalizedRanking"]]

        recent_preregistrations = ResearchhubPost.objects.filter(
            document_type="PREREGISTRATION",
            created_date__gte=datetime.now() - timedelta(days=30),
        ).order_by("-created_date")[:400]
        recent_preregistration_ids = [
            f"preregistration_{preregistration.id}"
            for preregistration in recent_preregistrations
        ]

        response = personalize_runtime.get_personalized_ranking(
            campaignArn=user_ranking_campaign_arn,
            inputList=recent_preregistration_ids,
            userId=user_id,
        )
        ranked_preregistration_ids = [
            item["itemId"] for item in response["personalizedRanking"]
        ]

        recent_comments = RhCommentModel.objects.filter(
            created_date__gte=datetime.now() - timedelta(days=14),
            is_removed=False,
        ).order_by("-created_date")[:400]
        recent_comment_ids = [f"comment_{comment.id}" for comment in recent_comments]

        response = personalize_runtime.get_personalized_ranking(
            campaignArn=user_ranking_campaign_arn,
            inputList=recent_comment_ids,
            userId=user_id,
        )
        ranked_comment_ids = [
            item["itemId"] for item in response["personalizedRanking"]
        ]

        ranked_ids = (
            ranked_bounty_ids[:2]
            + ranked_preregistration_ids[:1]
            + ranked_comment_ids[:7]
        )

        return ranked_ids

    def list(self, request, *args, **kwargs):
        user_id = request.query_params.get("user_id")
        if not user_id:
            return Response({"error": "user_id is required"}, status=400)

        personalize_runtime = boto3.client(
            "personalize-runtime", region_name="us-west-2"
        )

        ranked_object_ids = self._get_ranked_recent_object_ids(user_id)

        recs_campaign_arn = "arn:aws:personalize:us-west-2:794128250202:campaign/recs"

        filters = [
            # {
            #     "item_type": "bounty",
            #     "arn": "arn:aws:personalize:us-west-2:794128250202:filter/bounties-only",
            #     "num_results": 2,
            # },
            {
                "item_type": "paper",
                "arn": "arn:aws:personalize:us-west-2:794128250202:filter/papers-only",
                "num_results": 4,
            },
            {
                "item_type": "post",
                "arn": "arn:aws:personalize:us-west-2:794128250202:filter/posts-only",
                "num_results": 4,
            },
            # {
            #     "item_type": "preregistration",
            #     "arn": "arn:aws:personalize:us-west-2:794128250202:filter/preregistrations-only",
            #     "num_results": 1,
            # },
            {
                "item_type": "question",
                "arn": "arn:aws:personalize:us-west-2:794128250202:filter/questions-only",
                "num_results": 2,
            },
            # {
            #     "item_type": "comment",
            #     "arn": "arn:aws:personalize:us-west-2:794128250202:filter/comments-only",
            #     "num_results": 7,
            # },
        ]

        rec_ids = []
        for filter in filters:
            response = personalize_runtime.get_recommendations(
                campaignArn=recs_campaign_arn,
                userId=str(user_id),
                numResults=filter["num_results"],
                filterArn=filter["arn"],
            )
            # rec_ids = [item["itemId"] for item in response["itemList"]]
            rec_ids.extend([item["itemId"] for item in response["itemList"]])

        rec_ids = [item_id.split("_") for item_id in rec_ids if "_" in item_id]
        ranked_object_ids = [
            item_id.split("_") for item_id in ranked_object_ids if "_" in item_id
        ]
        paper_ids = [
            analytics_id[1] for analytics_id in rec_ids if analytics_id[0] == "paper"
        ]
        post_ids = [
            analytics_id[1]
            for analytics_id in rec_ids
            if analytics_id[0] == "question" or analytics_id[0] == "post"
        ]

        comment_ids = [
            analytics_id[1]
            for analytics_id in ranked_object_ids
            if analytics_id[0] == "comment"
        ]
        bounty_ids = [
            analytics_id[1]
            for analytics_id in ranked_object_ids
            if analytics_id[0] == "bounty"
        ]
        preregistration_ids = [
            analytics_id[1]
            for analytics_id in ranked_object_ids
            if analytics_id[0] == "preregistration"
        ]

        papers = Paper.objects.filter(id__in=paper_ids)
        comments = RhCommentModel.objects.filter(id__in=comment_ids)
        bounties = Bounty.objects.filter(id__in=bounty_ids)
        posts = ResearchhubPost.objects.filter(id__in=post_ids)
        preregistrations = ResearchhubPost.objects.filter(id__in=preregistration_ids)
        combined_queryset = list(
            chain(bounties, papers, comments, posts, preregistrations)
        )
        random.shuffle(combined_queryset)

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
