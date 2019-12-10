from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import (
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)
from rest_framework.response import Response

from .models import Hub
from .permissions import CreateHub, IsSubscribed, IsNotSubscribed
from .serializers import HubSerializer
from .filters import HubFilter

from utils.message import send_email_message


class HubViewSet(viewsets.ModelViewSet):
    queryset = Hub.objects.all()
    serializer_class = HubSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    permission_classes = [IsAuthenticatedOrReadOnly & CreateHub]
    filter_class = HubFilter
    search_fields = ('name')
    ordering = ['name']

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[IsAuthenticated & IsNotSubscribed]
    )
    def subscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.add(request.user)
            hub.save()

            if hub.is_locked and (
                len(hub.subscribers.all()) > Hub.UNLOCK_AFTER
            ):
                hub.unlock()

            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(e, status=400)

    @action(
        detail=True,
        methods=['post', 'put', 'patch'],
        permission_classes=[IsSubscribed]
    )
    def unsubscribe(self, request, pk=None):
        hub = self.get_object()
        try:
            hub.subscribers.remove(request.user)
            hub.save()
            return self._get_hub_serialized_response(hub, 200)
        except Exception as e:
            return Response(e, status=400)

    def _get_hub_serialized_response(self, hub, status_code):
        serialized = HubSerializer(hub)
        return Response(serialized.data, status=status_code)

    def _is_subscribed(self, user, hub):
        return user in hub.subscribers.all()

    @action(
        detail=True,
        methods=['post']
    )
    def invite_to_hub(self, request, pk=None):
        recipients = request.data['emails']
        subject = 'Researchhub Hub Invitation'
        hub = Hub.objects.get(id=pk)

        base_url = request.META['HTTP_ORIGIN']

        emailContext = {
            'hub_name': hub.name.capitalize(),
            'link': base_url + '/hubs/{}/'.format(hub.name),
            'opt_out': base_url + '/email/opt-out/'
        }

        subscribers = hub.subscribers.all()

        if subscribers:
            for subscriber in subscribers:
                if subscriber.email in recipients:
                    recipients.remove(subscriber.email)

        email_sent = send_email_message(
            recipients,
            'invite_to_hub_email.txt',
            subject,
            emailContext,
            'invite_to_hub_email.html'
        )
        response = {'email_sent': False}
        if email_sent == 1:
            response['email_sent'] = True
        return Response(response, status=200)
