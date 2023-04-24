from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny, IsAuthenticated

from user.models import Action
from user.serializers import DynamicActionSerializer


class CursorSetPagination(CursorPagination):
    page_size = 20
    cursor_query_param = "page"
    ordering = "-created_date"


class ContributionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Action.objects.all()
    permission_classes = [IsAuthenticated]
    pagination_class = CursorSetPagination
    filter_backends = (DjangoFilterBackend,)
    filterset_fields = ("hubs",)
    order_fields = ("created_date",)

    def _get_allowed_models(self):
        return (
            "researchhubpost",
            "rhcommentmodel",
            "paper",
            "hypothesis",
            "purchase",
            "bounty",
        )

    def get_filtered_queryset(self):
        qs = self.get_queryset()
        return self.filter_queryset(qs)

    def _get_latest_actions(self):
        actions = (
            self.get_filtered_queryset()
            .exclude(Q(is_removed=True) | Q(display=False))
            .filter(
                user__isnull=False,
                content_type__model__in=self._get_allowed_models(),
            )
            .select_related(
                "content_type",
                "user",
            )
            .prefetch_related(
                "item",
                "hubs",
                "user__author_profile",
            )
        )
        return actions

    def _get_latest_actions_context(self):
        context = {
            "usr_das_get_created_by": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "author_profile",
                ]
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "profile_image",
                    "first_name",
                    "last_name",
                ]
            },
            "usr_das_get_item": {
                "_include_fields": [
                    "abstract",
                    "amount",
                    "content_type",
                    "comment_content_json",
                    "discussion_post_type",
                    "hubs",
                    "id",
                    "item",
                    "paper_title",
                    "renderable_text",
                    "slug",
                    "title",
                    "thread",
                    "user",
                    "bounty_parent",
                    "unified_document",
                ]
            },
            "rep_dbs_get_parent": {
                "_include_fields": [
                    "id",
                ]
            },
            "rep_dbs_get_created_by": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                    "author_profile",
                ]
            },
            "rep_dbs_get_unified_document": {"_exclude_fields": "__all__"},
            "usr_das_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "hub_image",
                    "slug",
                ]
            },
            "pap_dps_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "hub_image",
                    "slug",
                ]
            },
            "pch_dps_get_source": {
                "_include_fields": [
                    "id",
                    "slug",
                    "paper_title",
                    "title",
                    "unified_document",
                    "plain_text",
                    "comment_content_json",
                    "thread",
                ]
            },
            "pch_dps_get_user": {
                "_include_fields": ["first_name", "last_name", "author_profile"]
            },
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "slug",
                    "documents",
                ]
            },
            "dis_dts_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "dis_dcs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "dis_drs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "doc_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "doc_dps_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "hub_image",
                    "slug",
                ]
            },
            "hyp_dhs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "renderable_text",
                    "title",
                    "slug",
                ]
            },
            "hyp_dhs_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "hub_image",
                    "slug",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "id",
                    "title",
                    "post_title",
                    "slug",
                    "renderable_text",
                ]
            },
            "rep_dbs_get_item": {
                "_include_fields": [
                    "id",
                    "documents",
                    "document_type",
                    "unified_document",
                    "thread",
                    "comment_content_json",
                ]
            },
            "rhc_dcs_get_created_by": {
                "_include_fields": [
                    "id",
                    "first_name",
                    "last_name",
                ]
            },
            "rhc_dcs_get_thread": {
                "_include_fields": ["content_object", "thread_type"]
            },
            "rhc_dts_get_content_object": {
                "_include_fields": [
                    "id",
                    "unified_document",
                ]
            },
        }
        return context

    @action(detail=False, methods=["get"], permission_classes=(AllowAny,))
    def latest_contributions(self, request):
        actions = self._get_latest_actions()
        page = self.paginate_queryset(actions)
        serializer = DynamicActionSerializer(
            page,
            many=True,
            context=self._get_latest_actions_context(),
            _include_fields=[
                "content_type",
                "created_by",
                "created_date",
                "hubs",
                "item",
            ],
        )
        data = serializer.data
        return self.get_paginated_response(data)
