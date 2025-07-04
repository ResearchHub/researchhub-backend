from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response

from discussion.constants.flag_reasons import FLAG_REASON_CHOICES, NOT_SPECIFIED
from discussion.models import Flag
from discussion.reaction_views import censor
from discussion.serializers import DynamicFlagSerializer, FlagSerializer
from mailing_list.lib import base_email_context
from notification.models import Notification
from researchhub.settings import EMAIL_DOMAIN
from researchhub_comment.models import RhCommentModel
from researchhub_comment.views.rh_comment_view import remove_bounties
from user.filters import AuditDashboardFilterBackend
from user.models import Action, User
from user.permissions import IsModerator, UserIsEditor
from user.serializers import DynamicActionSerializer, VerdictSerializer
from utils import sentry
from utils.message import send_email_message
from utils.models import SoftDeletableModel


class CursorSetPagination(CursorPagination):
    page_size = 10
    cursor_query_param = "page"


class AuditViewSet(viewsets.GenericViewSet):
    queryset = Action.objects.all()
    permission_classes = [UserIsEditor | IsModerator]
    pagination_class = CursorSetPagination
    filter_backends = (AuditDashboardFilterBackend,)
    order_fields = ("created_date", "verdict_created_date")

    def _get_allowed_models(self):
        return (
            ContentType.objects.get(model="rhcommentmodel"),
            ContentType.objects.get(model="researchhubpost"),
            ContentType.objects.get(model="paper"),
        )

    def get_queryset(self):
        if self.action == "flagged":
            return Flag.objects.select_related("content_type").prefetch_related(
                "verdict__created_by"
            )
        return super().get_queryset()

    def get_filtered_queryset(self):
        qs = self.get_queryset()
        return self.filter_queryset(qs)

    def _get_latest_actions(self):
        actions = (
            self.get_filtered_queryset()
            .filter(user__isnull=False, content_type__in=self._get_allowed_models())
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
                    "comment_content_json",
                    "uploaded_by",
                    "unified_document",
                    "abstract",
                    "amount",
                    "title",
                    "thread",
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
                    "documents",
                    "slug",
                    "title",
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
                    "renderable_text",
                ]
            },
            "rhc_dcs_get_created_by": {
                "_include_fields": ["author_profile", "first_name", "last_name"]
            },
            "rhc_dcs_get_thread": {"_include_fields": ["content_object"]},
            "rhc_dts_get_content_object": {
                "_include_fields": ["id", "unified_document", "thread_type"]
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
            {"count": count},
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
        flagger = request.user
        data = request.data
        flag_data = data.get("flag", [])

        with transaction.atomic():
            for f in flag_data:
                f["created_by"] = flagger.id

                if "reason_choice" not in f:
                    f["reason_choice"] = f.get("reason", NOT_SPECIFIED)

            flag_serializer = FlagSerializer(data=flag_data, many=True)
            flag_serializer.is_valid(raise_exception=True)
            flag_serializer.save()

            return Response({"flag": flag_serializer.data}, status=200)

    @action(detail=False, methods=["post"])
    def flag_and_remove(self, request):
        with transaction.atomic():
            flagger = request.user
            data = request.data
            flag_data = data.get("flag", [])
            verdict_data = data.get("verdict", {})
            for f in flag_data:
                f["created_by"] = flagger.id
            verdict_data["created_by"] = flagger.id

            flag_serializer = FlagSerializer(data=flag_data, many=True)
            flag_serializer.is_valid(raise_exception=True)
            flags = flag_serializer.save()

            verdict_serializer = None
            for flag in flags:
                verdict_data["flag"] = flag.id
                verdict_serializer = VerdictSerializer(data=verdict_data)
                verdict_serializer.is_valid(raise_exception=True)
                verdict = verdict_serializer.save()

                is_content_removed = verdict.is_content_removed
                if is_content_removed:
                    self._remove_flagged_content(flag)
                    self._send_notification_to_content_creator(
                        remover=flagger,
                        send_email=data.get("send_email", True),
                        verdict=verdict,
                    )

            return Response(
                {"flag": flag_serializer.data, "verdict": verdict_serializer.data},
                status=200,
            )

    @action(detail=False, methods=["post"])
    def dismiss_flagged_content(self, request):
        flagger = request.user
        data = request.data

        verdict_data = {}
        verdict_data["created_by"] = flagger.id
        verdict_data["is_content_removed"] = False

        try:
            flags = Flag.objects.filter(id__in=data.get("flag_ids", []))
            for flag in flags:
                available_reasons = list(map(lambda r: r[0], FLAG_REASON_CHOICES))
                verdict_choice = NOT_SPECIFIED
                if data.get("verdict_choice") in available_reasons:
                    verdict_choice = f'NOT_{data.get("verdict_choice")}'
                elif flag.reason_choice in available_reasons:
                    verdict_choice = f"NOT_{flag.reason_choice}"

                verdict_data["verdict_choice"] = verdict_choice
                verdict_data["flag"] = flag.id
                verdict_serializer = VerdictSerializer(data=verdict_data)
                verdict_serializer.is_valid(raise_exception=True)
                verdict_serializer.save()
        except Exception as e:
            print("e", e)
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
        flagger = request.user
        data = request.data

        verdict_data = {}
        verdict_data["created_by"] = flagger.id
        verdict_data["is_content_removed"] = True

        with transaction.atomic():
            flags = Flag.objects.filter(id__in=data.get("flag_ids", []))
            for flag in flags.iterator():
                available_reasons = list(map(lambda r: r[0], FLAG_REASON_CHOICES))
                verdict_choice = NOT_SPECIFIED
                if data.get("verdict_choice") in available_reasons:
                    verdict_choice = data.get("verdict_choice")
                elif flag.reason_choice in available_reasons:
                    verdict_choice = flag.reason_choice

                verdict_data["verdict_choice"] = verdict_choice
                verdict_data["flag"] = flag.id
                verdict_serializer = VerdictSerializer(data=verdict_data)
                verdict_serializer.is_valid(raise_exception=True)
                verdict = verdict_serializer.save()
                flag.verdict_created_date = verdict.created_date
                flag.save()

                self._remove_flagged_content(flag)
                try:
                    self._send_notification_to_content_creator(
                        remover=flagger,
                        send_email=data.get("send_email", True),
                        verdict=verdict,
                    )
                except Exception as e:
                    sentry.log_error(e, message="Content Removal notification not sent")

            return Response(
                {},
                status=200,
            )

    @action(detail=False, methods=["post"])
    def remove_flagged_paper_pdf(self, request):
        flagger = request.user
        data = request.data

        verdict_data = {}
        verdict_data["created_by"] = flagger.id
        verdict_data["is_paper_pdf_removed"] = True

        with transaction.atomic():
            flags = Flag.objects.filter(id__in=data.get("flag_ids", []))
            for flag in flags.iterator():
                if flag.content_type != ContentType.objects.get(
                    app_label="paper", model="paper"
                ):
                    continue

                available_reasons = list(map(lambda r: r[0], FLAG_REASON_CHOICES))
                verdict_choice = NOT_SPECIFIED
                if data.get("verdict_choice") in available_reasons:
                    verdict_choice = data.get("verdict_choice")
                elif flag.reason_choice in available_reasons:
                    verdict_choice = flag.reason_choice

                verdict_data["verdict_choice"] = verdict_choice
                verdict_data["flag"] = flag.id
                verdict_serializer = VerdictSerializer(data=verdict_data)
                verdict_serializer.is_valid(raise_exception=True)
                verdict = verdict_serializer.save()
                flag.verdict_created_date = verdict.created_date
                flag.save()

                self._remove_flagged_paper_pdf(flag)

            return Response(
                {},
                status=200,
            )

    def _remove_flagged_paper_pdf(self, flag):
        with transaction.atomic():
            paper = flag.item
            # we keep the PDF/file but set this flag so that we don't show the PDF
            paper.is_pdf_removed_by_moderator = True
            paper.save()

    def _remove_flagged_content(self, flag):
        with transaction.atomic():
            flag_item = flag.item
            if isinstance(flag_item, RhCommentModel):
                remove_bounties(flag_item)
            censor_response = censor(flag.verdict.created_by, flag_item)

            if isinstance(flag_item, RhCommentModel):
                flag_item.refresh_related_discussion_count()

            return censor_response

    def _send_notification_to_content_creator(self, verdict, remover, send_email=True):
        flag = verdict.flag
        model_class = flag.content_type.model_class()

        if issubclass(model_class, SoftDeletableModel):
            flagged_content = model_class.all_objects.get(id=flag.object_id)
        else:
            flagged_content = model_class.objects.get(id=flag.object_id)

        if flag.content_type.name == "paper":
            content_creator = flagged_content.uploaded_by
        else:
            content_creator = flagged_content.created_by
        Action.objects.create(
            item=verdict, user=remover, content_type=get_content_type_for_model(verdict)
        )

        if content_creator is None:
            return

        anon_remover = User.objects.get_community_account()
        notification = Notification.objects.create(
            action_user=anon_remover,
            item=verdict,
            recipient=content_creator,
            unified_document=flagged_content.unified_document,
            notification_type=Notification.FLAGGED_CONTENT_VERDICT,
        )
        notification.send_notification()
        if send_email:
            self._send_email_notification_to_content_creator(
                flag, notification, verdict
            )

    def _send_email_notification_to_content_creator(self, flag, notification, verdict):
        receiver = notification.recipient
        action = Action.objects.get(
            content_type=flag.content_type, object_id=flag.object_id
        )
        name = f"{receiver.first_name} {receiver.last_name}"
        email_context = {
            **base_email_context,
            "user_name": name,
            "verdict_choice": verdict.verdict_choice.replace("_", " "),
            "actions": (action.email_context(),),
        }

        recipient = [receiver.email]
        subject = "ResearchHub | Notice of Flagged and Removed Content"
        send_email_message(
            recipient,
            "flagged_and_removed_content.txt",
            subject,
            email_context,
            "flagged_and_removed_content.html",
            f"ResearchHub Digest <digest@{EMAIL_DOMAIN}>",
        )
