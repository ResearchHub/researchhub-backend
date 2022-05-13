import functools
import operator

import django_filters.rest_framework
from django.db.models import Prefetch, Q
from django.db.models.expressions import OuterRef, Subquery
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from discussion.models import BaseComment
from discussion.reaction_models import Flag
from discussion.reaction_serializers import FlagSerializer
from discussion.serializers import DynamicFlagSerializer
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Action
from user.serializers import DynamicActionSerializer, VerdictSerializer


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

    def _get_flagged_actions(self):
        flagged_contributions = self._get_flagged_content()
        return flagged_contributions

        # actions = self.get_filtered_queryset()
        # actions = Action.objects.all().annotate(
        #     reason=Subquery(Flag.objects.all().filter(content_type_id=OuterRef('content_type_id'), object_id=OuterRef("object_id")).values('reason'))
        # ).filter(reason__isnull=False)
        # return actions

        # actions = self.get_queryset().filter(
        #     functools.reduce(
        #         operator.or_,
        #         (
        #             Q(content_type_id=content_type_id, object_id=object_id)
        #             for content_type_id, object_id in flagged_contributions.values_list(
        #                 "content_type_id", "object_id"
        #             )
        #         ),
        #     )
        # ).annotate(
        #     reason=Subquery(flagged_contributions.values('reason'))
        # ).select_related("user").prefetch_related("item", "user__author_profile")
        # return actions

    def _get_latest_actions(self):
        # actions = (
        #     self.get_filtered_queryset()
        #     .filter(user__isnull=False, content_type__model__in=self.models)
        #     .exclude(
        #         functools.reduce(
        #             operator.or_,
        #             (
        #                 Q(content_type_id=content_type_id, object_id=object_id)
        #                 for content_type_id, object_id in self._get_flagged_content().values_list(
        #                     "content_type_id", "object_id"
        #                 )
        #             ),
        #         )
        #     )
        #     .select_related("user")
        #     .prefetch_related("item", "user__author_profile")
        # )
        # return actions

        actions = (
            self.get_filtered_queryset()
            .filter(user__isnull=False, content_type__model__in=self.models)
            .annotate(
                ct=Subquery(
                    Flag.objects.filter(
                        content_type_id=OuterRef("content_type_id")
                    ).values("content_type_id")[:1]
                ),
                ob=Subquery(
                    Flag.objects.filter(object_id=OuterRef("object_id")).values(
                        "object_id"
                    )[:1]
                ),
            )
            .exclude(ct__isnull=False, ob__isnull=False)
            .select_related("user")
            .prefetch_related(
                "item",
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
                ]
            },
            "usr_das_get_item": {
                "_include_fields": [
                    "id",
                    "created_by",
                    "uploaded_by",
                    "unified_document",
                    "source",
                    "amount",
                    "plain_text",
                    "title",
                    "slug",
                    "renderable_text",
                ]
            },
            "usr_das_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                ]
            },
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                ]
            },
            "pap_dps_get_uploaded_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
            },
            "dis_dts_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "dis_dts_get_created_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
            },
            "dis_dcs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "dis_dcs_get_created_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
            },
            "dis_drs_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "dis_drs_get_created_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
            },
            "doc_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "document_type",
                    "documents",
                    "slug",
                ]
            },
            "doc_dps_get_created_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "id",
                    "title",
                    "post_title",
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
            "hyp_dhs_get_created_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
            },
        }
        context["dis_dfs_get_item"] = context["usr_das_get_item"]
        context["dis_dfs_get_created_by"] = context["usr_das_get_created_by"]
        context["dis_dfs_get_hubs"] = context["usr_das_get_hubs"]
        return context

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def flagged(self, request):
        # actions = self._get_flagged_actions()
        # page = self.paginate_queryset(actions)
        # serializer = DynamicActionSerializer(
        #     page,
        #     many=True,
        #     context=self._get_latest_actions_context(),
        #     _include_fields=[
        #         "id",
        #         "content_type",
        #         "created_by",
        #         "item",
        #         "created_date",
        #         "reason",
        #     ],
        # )
        # data = serializer.data
        # return self.get_paginated_response(data)

        actions = self._get_flagged_content()
        page = self.paginate_queryset(actions)
        serializer = DynamicFlagSerializer(
            page,
            many=True,
            context=self._get_latest_actions_context(),
            _include_fields=[
                "content_type",
                "flagged_by",
                "created_date",
                "item",
                "reason",
                "hubs",
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
                "content_type",
                # "created_by",
                "item",
                "created_date",
                "hubs",
            ],
        )
        data = serializer.data
        return self.get_paginated_response(data)

    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def flag(self, request):
        moderator = request.user
        data = request.data
        flag_data = data.get("flag", [])
        for f in flag_data:
            f["created_by"] = moderator.id

        flag_serializer = FlagSerializer(data=flag_data, many=True)
        flag_serializer.is_valid(raise_exception=True)
        flag_serializer.save()

        return Response({"flag": flag_serializer.data}, status=200)

    # TODO: Permissions
    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def flag_and_remove(self, request):
        moderator = request.user
        data = request.data
        flag_data = data.get("flag", [])
        verdict_data = data.get("verdict", {})
        for f in flag_data:
            f["created_by"] = moderator.id
        verdict_data["created_by"] = moderator.id

        flag_serializer = FlagSerializer(data=flag_data, many=True)
        flag_serializer.is_valid(raise_exception=True)
        flags = flag_serializer.save()

        for flag in flags:
            verdict_data["flag"] = flag.id
            verdict_serializer = VerdictSerializer(data=verdict_data)
            verdict_serializer.is_valid(raise_exception=True)
            verdict = verdict_serializer.save()

            is_content_removed = verdict.is_content_removed
            if is_content_removed:
                item = flag.item
                if isinstance(item, BaseComment):
                    item.is_removed = is_content_removed
                    item.save()
                else:
                    unified_document = item.unified_document
                    unified_document.is_removed = is_content_removed
                    unified_document.save()

        return Response(
            {"flag": flag_serializer.data, "verdict": verdict_serializer.data},
            status=200,
        )
