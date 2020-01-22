from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
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
from user.models import Action
from user.serializers import UserActions
from utils.http import PATCH, POST, PUT, GET
from utils.message import send_email_message
from utils.sentry import log_error


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
        methods=[POST, PUT, PATCH],
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
        methods=[POST, PUT, PATCH],
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
        methods=[POST]
    )
    def invite_to_hub(self, request, pk=None):
        recipients = request.data.get('emails', [])

        if len(recipients) < 1:
            message = 'Field `emails` can not be empty'
            error = ValidationError(message)
            return Response(error.detail, status=400)

        subject = 'Researchhub Hub Invitation'
        hub = Hub.objects.get(id=pk)

        base_url = request.META['HTTP_ORIGIN']

        emailContext = {
            'hub_name': hub.name.capitalize(),
            'link': base_url + '/hubs/{}/'.format(hub.name),
            'opt_out': base_url + '/email/opt-out/'
        }

        subscriber_emails = hub.subscribers.all().values_list(
            'email',
            flat=True
        )

        # Don't send to hub subscribers
        if len(subscriber_emails) > 0:
            for recipient in recipients:
                if recipient in subscriber_emails:
                    recipients.remove(recipient)

        result = send_email_message(
            recipients,
            'invite_to_hub_email.txt',
            subject,
            emailContext,
            'invite_to_hub_email.html'
        )

        response = {'email_sent': False, 'result': result}
        if len(result['success']) > 0:
            response = {'email_sent': True, 'result': result}

        return Response(response, status=200)

    @action(
        detail=False,
        methods=[GET]
    )
    def latest_hub_actions(self, request):
        actions = Action.objects.all()
        try:
            hub_id = request.query_params.get('hub')
            if int(hub_id) != 0:
                actions = Action.objects.filter(hubs=hub_id)
        except Exception as e:
            log_error(e)
            return Response(str(e), status=400)

        actions = actions.order_by('created_date')

        page = self.paginate_queryset(actions)

        if page is not None:
            data = UserActions(data=page).serialized
            return self.get_paginated_response(data)

        data = UserActions(data=actions).serialized
        return Response(data)
