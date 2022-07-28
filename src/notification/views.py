from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from notification.models import Notification
from notification.serializers import (
    DynamicNotificationSerializer,
    NotificationSerializer,
)
from utils.http import PATCH


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer

    def get_permissions(self):
        """Instantiates and returns the list of permissions that this view
        requires.
        """
        if (
            (self.action == "list")
            or (self.action == "partial_update")
            or (self.action == "mark_read")
        ):
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        bulletpoint_ct = ContentType.objects.get(model="bulletpoint")
        bulletpoint_vote_ct = ContentType.objects.get(
            app_label="bullet_point", model="vote"
        )
        summary_ct = ContentType.objects.get(model="summary")
        summary_vote_ct = ContentType.objects.get(app_label="summary", model="vote")
        user = self.request.user
        notifications = Notification.objects.filter(recipient=user)
        notifications = notifications.exclude(
            action__content_type__in=[
                bulletpoint_ct,
                bulletpoint_vote_ct,
                summary_ct,
                summary_vote_ct,
            ]
        )
        notifications = (
            notifications.order_by("-created_date")
            .select_related(
                "action__content_type",
                "action_user",
                "action_user__author_profile",
                "recipient",
                "recipient__author_profile",
                "unified_document",
                "unified_document__paper",
                "unified_document__hypothesis",
            )
            .prefetch_related(
                "action__item",
                "unified_document__posts",
            )
        )
        return notifications

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        context = self._get_context()

        page = self.paginate_queryset(queryset)
        serializer = DynamicNotificationSerializer(
            page,
            _include_fields=[
                "action",
                "action_user",
                "created_date",
                "id",
                "read",
                "read_date",
                "recipient",
                "unified_document",
            ],
            context=context,
            many=True,
        )
        data = serializer.data
        return self.get_paginated_response(data)

    def partial_update(self, request, *args, **kwargs):
        if request.data.get("read") is True:
            request.data["read_date"] = timezone.now()
        response = super().partial_update(request, *args, **kwargs)
        return response

    @action(detail=False, methods=[PATCH], permission_classes=[IsAuthenticated])
    def mark_read(self, request, pk=None):
        ids = request.data.get("ids", [])
        user = request.user
        Notification.objects.filter(recipient=user, id__in=ids).update(
            read=True, read_date=timezone.now()
        )
        return Response("Success", status=status.HTTP_200_OK)

    def _get_context(self):
        context = {
            "not_dns_get_action": {
                "_include_fields": [
                    "content_type",
                    "item",
                ]
            },
            "not_dns_get_action_user": {
                "_include_fields": [
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "not_dns_get_recipient": {
                "_include_fields": [
                    "author_profile",
                    "first_name",
                    "last_name",
                ]
            },
            "not_dns_get_unified_document": {
                "_include_fields": [
                    "documents",
                    "document_type",
                ]
            },
            "doc_duds_get_documents": {
                "_include_fields": [
                    "id",
                    "paper_title",
                    "slug",
                    "title",
                ]
            },
            "usr_das_get_item": {
                "_include_fields": [
                    "amount",
                    "content_type",
                    "expiration_date",
                    "flagged_content_name",
                    "id",
                    "is_content_removed",
                    "paper_status",
                    "paper",
                    "plain_text",
                    "verdict_choice",
                ],
            },
            "usr_dus_get_author_profile": {
                "_include_fields": [
                    "id",
                    "profile_image",
                ]
            },
            "pap_dpss_get_paper": {"_include_fields": ["id", "title"]},
            "pap_dps_get_unified_document": {
                "_include_fields": [
                    "id",
                    "title",
                    "document_type",
                    "slug",
                ]
            },
        }
        return context
