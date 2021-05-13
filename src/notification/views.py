from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from utils.http import PATCH

from notification.models import Notification
from notification.serializers import NotificationSerializer


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer

    def get_permissions(self):
        """Instantiates and returns the list of permissions that this view
        requires.
        """
        if (
            (self.action == 'list')
            or (self.action == 'partial_update')
            or (self.action == 'mark_read')
        ):
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        return Notification.objects.filter(recipient=user).order_by(
            '-created_date'
        )

    def partial_update(self, request, *args, **kwargs):
        if request.data.get('read') is True:
            request.data['read_date'] = timezone.now()
        response = super().partial_update(request, *args, **kwargs)
        return response

    @action(
        detail=False,
        methods=[PATCH],
        permission_classes=[IsAuthenticated]
    )
    def mark_read(self, request, pk=None):
        ids = request.data.get('ids', [])
        user = request.user
        Notification.objects.filter(
            recipient=user,
            id__in=ids
        ).update(read=True, read_date=timezone.now())
        return Response('Success', status=status.HTTP_200_OK)
