import functools
import operator

import django_filters.rest_framework
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from discussion.models import Flag
from discussion.serializers import DynamicFlagSerializer
from user.models import Action
from user.serializers import DynamicActionSerializer


class CursorSetPagination(CursorPagination):
    page_size = 10
    cursor_query_param = "page"
    ordering = "-created_date"


class AuditViewSet(viewsets.GenericViewSet):
    # TODO: Permissions
    queryset = Action.objects.all()
    permission_classes = [AllowAny]
    pagination_class = CursorSetPagination
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend]
    filterset_fields = ["hubs"]
    models = [
        "thread",
        "comment",
        "reply",
        "researchhubpost",
        "paper",
        "hypothesis",
    ]

    def get_filtered_queryset(self):
        return self.filter_queryset(self.get_queryset())

    def _get_flagged_content(self):
        flagged_contributions = Flag.objects.all().select_related("content_type")
        return flagged_contributions

    def _get_latest_actions(self):
        actions = (
            self.get_queryset()
            .filter(user__isnull=False, content_type__model__in=self.models)
            .exclude(
                functools.reduce(
                    operator.or_,
                    (
                        Q(content_type_id=content_type_id, object_id=object_id)
                        for content_type_id, object_id in self._get_flagged_content().values_list(
                            "content_type_id", "object_id"
                        )
                    ),
                )
            )
            .select_related("user")
            .prefetch_related("item", "user__author_profile")
        )
        return actions

        # actions = (
        #     self.get_filtered_queryset()
        #     .filter(user__isnull=False, content_type__model__in=self.models)
        #     .exclude(content_type_id=Subquery(Flag.objects.filter(content_type_id=OuterRef("content_type_id")).values("content_type_id")[:1]))#, object_id=Subquery(Flag.objects.filter(object_id=OuterRef("object_id")).values("object_id")[:1]))
        #     .select_related("user")
        #     .prefetch_related("item", "user__author_profile")
        # )
        # return actions

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
                ]
            },
            "usr_das_get_item": {
                "_include_fields": [
                    "unified_document",
                    "content_type",
                    "source",
                    "user",
                    "amount",
                    "plain_text",
                    "title",
                    "slug",
                ]
            },
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
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
            "hyp_dhs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "renderable_text",
                    "title",
                    "slug",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "id",
                    "title",
                    "post_title",
                    "slug",
                ]
            },
        }
        context["dis_dfs_get_item"] = context["usr_das_get_item"]
        context["dis_dfs_get_created_by"] = context["usr_das_get_created_by"]
        return context

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def flagged(self, request):
        actions = self._get_flagged_content()
        page = self.paginate_queryset(actions)
        serializer = DynamicFlagSerializer(
            page,
            many=True,
            context=self._get_latest_actions_context(),
            _include_fields=[
                "id",
                "content_type",
                "created_by",
                "created_date",
                "item",
                "reason",
            ],
        )
        data = serializer.data
        return self.get_paginated_response(data)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def contributions(self, request):
        actions = self._get_latest_actions()
        page = self.paginate_queryset(actions)
        serializer = DynamicActionSerializer(
            page,
            many=True,
            context=self._get_latest_actions_context(),
            _include_fields=[
                "id",
                "content_type",
                "created_by",
                "item",
                "created_date",
            ],
        )
        data = serializer.data
        return self.get_paginated_response(data)
