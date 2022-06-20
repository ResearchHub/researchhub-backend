from django.contrib.contenttypes.models import ContentType
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from discussion.models import Thread
from peer_review.models import PeerReview, PeerReviewDecision
from peer_review.permissions import (
    IsAllowedToCreateDecision,
    IsAllowedToCreateOrUpdatePeerReview,
)
from peer_review.serializers import PeerReviewDecisionSerializer, PeerReviewSerializer
from reputation.models import Contribution
from reputation.serializers import DynamicContributionSerializer
from utils.http import DELETE, GET, PATCH, POST, PUT


class PeerReviewViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
        IsAllowedToCreateOrUpdatePeerReview,
    ]
    serializer_class = PeerReviewSerializer
    queryset = PeerReview.objects.all()

    @action(
        detail=True,
        methods=[GET],
    )
    def timeline(self, request, pk=None):
        thread_content_type = ContentType.objects.get_for_model(Thread)
        peer_review_decision_content_type = ContentType.objects.get_for_model(
            PeerReviewDecision
        )

        contribution_type = [
            Contribution.PEER_REVIEWER,
            Contribution.COMMENTER,
        ]

        qs = (
            Contribution.objects.filter(
                unified_document__is_removed=False,
                contribution_type__in=contribution_type,
                content_type_id__in=[
                    thread_content_type,
                    peer_review_decision_content_type,
                ],
            )
            .select_related(
                "content_type",
                "user",
                "user__author_profile",
                "unified_document",
            )
            .prefetch_related(
                "unified_document__hubs",
            )
        )

        page = self.paginate_queryset(qs)
        context = self._get_contribution_context()
        serializer = DynamicContributionSerializer(
            page,
            _include_fields=[
                "contribution_type",
                "created_date",
                "id",
                "source",
                "created_by",
                "unified_document",
                "author",
            ],
            context=context,
            many=True,
        )

        response = self.get_paginated_response(serializer.data)
        return response

    @action(detail=True, methods=[POST], permission_classes=[IsAllowedToCreateDecision])
    def create_decision(self, request, pk=None):
        review = self.get_object()
        request.data["unified_document"] = review.unified_document.id

        serializer = self.get_serializer(data=request.data)
        serializer.context["peer_review"] = review
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response(serializer.data)

    def get_serializer_class(self):
        if self.action == "create_decision":
            return PeerReviewDecisionSerializer
        else:
            return self.serializer_class

    def _get_contribution_context(self):
        context = {
            "request": self.request,
            "doc_dps_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "doc_duds_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dts_get_created_by": {
                "_include_fields": [
                    "id",
                    "author_profile",
                ]
            },
            "dis_dcs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "dis_drs_get_created_by": {
                "_include_fields": [
                    "author_profile",
                    "id",
                ]
            },
            "pap_dps_get_user_vote": {
                "_include_fields": [
                    "id",
                    "created_by",
                    "created_date",
                    "vote_type",
                ]
            },
            "pap_dps_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "doc_dps_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_drs_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dcs_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dts_get_user_vote": {
                "_include_fields": [
                    "id",
                    "content_type",
                    "created_by",
                    "created_date",
                    "vote_type",
                    "item",
                ]
            },
            "dis_dts_get_comments": {
                "_include_fields": [
                    "created_by",
                    "created_date",
                    "updated_date",
                    "created_location",
                    "external_metadata",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "replies",
                    "reply_count",
                    "score",
                    "source",
                    "text",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                ]
            },
            "dis_dcs_get_replies": {
                "_include_fields": [
                    "created_by",
                    "created_location",
                    "id",
                    "is_created_by_editor",
                    "is_public",
                    "is_removed",
                    "paper_id",
                    "parent",
                    "plain_text",
                    "promoted",
                    "score",
                    "text",
                    "thread_id",
                    "user_flag",
                    "user_vote",
                    "created_date",
                    "updated_date",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "promoted",
                    "abstract",
                    "aggregate_citation_consensus",
                    "created_by",
                    "created_date",
                    "hot_score",
                    "hubs",
                    "id",
                    "discussion_count",
                    "paper_title",
                    "preview_img",
                    "renderable_text",
                    "score",
                    "slug",
                    "title",
                    "uploaded_by",
                    "uploaded_date",
                    "user_vote",
                ]
            },
            "rep_dcs_get_author": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "profile_image",
                ]
            },
            "rep_dcs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "hubs",
                ]
            },
            "rep_dcs_get_source": {
                "_include_fields": [
                    "replies",
                    "content_type",
                    "promoted",
                    "comments",
                    "discussion_type",
                    "amount",
                    "paper_title",
                    "slug",
                    "block_key",
                    "comment_count",
                    "context_title",
                    "created_by",
                    "created_date",
                    "created_location",
                    "entity_key",
                    "external_metadata",
                    "hypothesis",
                    "citation",
                    "id",
                    "is_public",
                    "is_removed",
                    "paper_slug",
                    "paper",
                    "post_slug",
                    "post",
                    "plain_text",
                    "promoted",
                    "score",
                    "source",
                    "text",
                    "title",
                    "user_flag",
                    "user_vote",
                    "was_edited",
                    "document_meta",
                ]
            },
            "dis_dts_get_paper": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "dis_dts_get_post": {
                "_include_fields": [
                    "id",
                    "slug",
                ]
            },
            "doc_duds_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
            "hyp_dhs_get_hubs": {
                "_include_fields": [
                    "name",
                    "slug",
                ]
            },
        }
        return context
