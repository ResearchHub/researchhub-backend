from django.shortcuts import render
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated, IsAdminUser

from notification.models import Notification
from notification.serializers import NotificationSerializer


# TODO: Remove before merge
def test(request):
    return render(request, 'websocket_test.html')


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer

    def get_permissions(self):
        """Instantiates and returns the list of permissions that this view
        requires.
        """
        if self.action == 'list' or self.action == 'partial_update':
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        return Notification.objects.filter(recipient=user)

    def partial_update(self, request, *args, **kwargs):
        if request.data.get('read') is True:
            request.data['read_date'] = timezone.now()
        response = super().partial_update(request, *args, **kwargs)
        return response
