from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from notification.models import Notification
from notification.serializers import (
    DynamicNotificationSerializer,
    NotificationSerializer,
    get_notification_context,
)


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
            or (self.action == "unread_count")
        ):
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        notifications = Notification.objects.filter(recipient=user).exclude(
            notification_type=Notification.DEPRECATED
        )
        return notifications.order_by("-created_date")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        context = get_notification_context()

        page = self.paginate_queryset(queryset)
        serializer = DynamicNotificationSerializer(
            page,
            _include_fields=[
                "body",
                "action_user",
                "created_date",
                "extra",
                "id",
                "navigation_url",
                "notification_type",
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

    @action(detail=False, methods=["PATCH"], permission_classes=[IsAuthenticated])
    def mark_read(self, request, pk=None):
        user = request.user
        Notification.objects.filter(recipient=user).update(
            read=True, read_date=timezone.now()
        )
        return Response("Success", status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["GET"],
    )
    def unread_count(self, request):
        unread_count = (
            self.get_queryset().filter(read=False, recipient_id=request.user.id).count()
        )
        return Response({"count": unread_count}, status=status.HTTP_200_OK)
