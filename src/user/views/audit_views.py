import functools
from http.client import INTERNAL_SERVER_ERROR
import operator

from django.db.models import Prefetch, Q
from django.db.models.expressions import OuterRef, Subquery
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from discussion.constants.flag_reasons import NOT_SPECIFIED

from discussion.models import BaseComment
from discussion.reaction_models import Flag
from discussion.reaction_serializers import FlagSerializer
from discussion.serializers import DynamicFlagSerializer
from paper.related_models.paper_model import Paper
from user.filters import AuditDashboardFilterBackend
from user.models import Action
from user.permissions import UserIsEditor
from user.serializers import DynamicActionSerializer, VerdictSerializer
from utils import sentry

class CursorSetPagination(CursorPagination):
    page_size = 10
    cursor_query_param = "page"
    ordering = "-created_date"


class AuditViewSet(viewsets.GenericViewSet):
    queryset = Action.objects.all()
    # permission_classes = [IsAuthenticated, UserIsEditor]
    permission_classes = [AllowAny]
    pagination_class = CursorSetPagination
    filter_backends = (AuditDashboardFilterBackend,)
    models = (
        "thread",
        "comment",
        "reply",
        "researchhubpost",
        "paper",
        "hypothesis",
    )

    def get_queryset(self):
        if self.action == "flagged":
            return (
                Flag.objects.all()
                .select_related("content_type")
                .prefetch_related("verdict__created_by")
            )
        return super().get_queryset()

    def get_filtered_queryset(self):
        qs = self.get_queryset()
        return self.filter_queryset(qs)

    # TODO: Delete
    def _get_flagged_content(self):
        flagged_contributions = Flag.objects.all().select_related("content_type")
        return flagged_contributions

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
                    "created_date",
                    "uploaded_by",
                    "unified_document",
                    "source",
                    "amount",
                    "plain_text",
                    "title",
                    "slug",
                ]
            },
            "usr_das_get_hubs": {
                "_include_fields": [
                    "id",
                    "name",
                    "slug",
                ]
            },
            "usr_dvs_get_created_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
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
            "dis_dfs_get_verdict": {
                "_include_fields": ["verdict_choice", "created_by", "created_date"]
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
                    "document_type",
                    "documents",
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

    @action(detail=False, methods=["get"])
    def flagged(self, request):
        query_params = request.query_params
        verdict = query_params.get("verdict", None)
        actions = self.get_filtered_queryset()
        print('actions', actions.count())
        page = self.paginate_queryset(actions)
        _include_fields = [
            "content_type",
            "flagged_by",
            "created_date",
            "item",
            "reason",
            "reason_choice",
            "hubs",
            "id",
        ]
        if verdict is not None:
            _include_fields.append("verdict")

        serializer = DynamicFlagSerializer(
            page,
            many=True,
            context=self._get_latest_actions_context(),
            _include_fields=_include_fields,
        )
        data = serializer.data
        return self.get_paginated_response(data)

    @action(detail=False, methods=["get"])
    def flagged_count(self, request):
        count = Flag.objects.filter(verdict__isnull=True).count()
        return Response(
            {'count': count},
            status=status.HTTP_200_OK,
        )        

    @action(detail=False, methods=["get"])
    def contributions(self, request):
        actions = self._get_latest_actions()
        page = self.paginate_queryset(actions)
        serializer = DynamicActionSerializer(
            page,
            many=True,
            context=self._get_latest_actions_context(),
            _include_fields=[
                "content_type",
                "item",
                "created_date",
                "hubs",
            ],
        )
        data = serializer.data
        return self.get_paginated_response(data)

    @action(detail=False, methods=["post"])
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

    @action(detail=False, methods=["post"])
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

        verdict_serializer = None
        try: 
            for flag in flags:
                verdict_data["flag"] = flag.id
                verdict_serializer = VerdictSerializer(data=verdict_data)
                verdict_serializer.is_valid(raise_exception=True)
                verdict = verdict_serializer.save()

                is_content_removed = verdict.is_content_removed
                if is_content_removed:
                    self._remove_flagged_content(flag)

        except Exception as e:
            print('e', e)
            sentry.log_error(e)

            return Response(
                {},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,  
            )

        return Response(
            {"flag": flag_serializer.data, "verdict": verdict_serializer.data},
            status=200,
        )

    @action(detail=False, methods=["post"])
    def dismiss_flagged_content(self, request):
        moderator = request.user
        data = request.data

        verdict_data = {}
        verdict_data["created_by"] = moderator.id
        verdict_data["is_content_removed"] = False

        try:
            flags = Flag.objects.filter(id__in=data.get("flag_ids", []))
            for flag in flags:
                default_value = None
                if flag.reason_choice:
                    default_value = f'NOT_{flag.reason_choice}'
                else:
                    default_value = NOT_SPECIFIED

                verdict_data["verdict_choice"] = data.get("verdict_choice", default_value)
                verdict_data["flag"] = flag.id
                verdict_serializer = VerdictSerializer(data=verdict_data)
                verdict_serializer.is_valid(raise_exception=True)
                verdict = verdict_serializer.save()
        except Exception as e:
            print('e', e)
            sentry.log_error(e)
           
            return Response(
                {},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,  
            )

        return Response(
            {},
            status=200,
        )

    @action(detail=False, methods=["post"])
    def remove_flagged_content(self, request):
        moderator = request.user
        data = request.data

        verdict_data = {}
        verdict_data["created_by"] = moderator.id
        verdict_data["is_content_removed"] = True

        try:
            flags = Flag.objects.filter(id__in=data.get("flag_ids", []))
            for flag in flags:
                default_value = None
                if flag.reason_choice:
                    default_value = flag.reason_choice
                else:
                    default_value = NOT_SPECIFIED

                verdict_data["verdict_choice"] = data.get("verdict_choice", flag.reason_choice)
                verdict_data["flag"] = flag.id
                verdict_serializer = VerdictSerializer(data=verdict_data)
                verdict_serializer.is_valid(raise_exception=True)
                verdict = verdict_serializer.save()

                self._remove_flagged_content(flag)

        except Exception as e:
            print('e', e)
            sentry.log_error(e)   

            return Response(
                {},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,  
            )

        return Response(
            {},
            status=200,
        )

    def _remove_flagged_content(self, flag):
        item = flag.item
        if isinstance(item, BaseComment):
            item.is_removed = True
            item.save()
        else:
            unified_document = item.unified_document
            unified_document.is_removed = True
            unified_document.save()

            inner_doc = unified_document.get_document()
            if isinstance(inner_doc, Paper):
                inner_doc.is_removed = True
                inner_doc.reset_cache()
                inner_doc.save()
