from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action

from analytics.models import PaperEvent, WebsiteVisits
from analytics.permissions import UpdateOrDelete
from analytics.serializers import (
    PaperEventSerializer,
    WebsiteVisitsSerializer
)
from analytics.amplitude import Amplitude
from reputation.models import Contribution
from reputation.tasks import create_contribution


class WebsiteVisitsViewSet(viewsets.ModelViewSet):
    queryset = WebsiteVisits.objects.all()
    serializer_class = WebsiteVisitsSerializer
    http_method_names = ['post']
    permission_classes = ()


class PaperEventViewSet(viewsets.ModelViewSet):
    queryset = PaperEvent.objects.all()
    serializer_class = PaperEventSerializer
    permission_classes = [UpdateOrDelete]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = [
        'paper',
        'created_date',
        'created_location',
        'interaction',
        'paper_is_boosted',
    ]
    ordering = ['-created_date']
    ordering_fields = ['created_date']

    def create(self, request, *args, **kwargs):
        user = request.user
        if not user.is_anonymous:
            request.data['user'] = user.id

        created_location = request.data.get('created_location')
        if created_location is not None:
            created_location = created_location.upper()
            request.data['created_location'] = created_location
        else:
            return Response(
                'Missing required field `created_location`',
                status=status.HTTP_400_BAD_REQUEST
            )

        interaction = request.data.get('interaction', None)
        if interaction is not None:
            interaction = interaction.upper()
            request.data['interaction'] = interaction

        paper_id = request.data['paper']
        res = super().create(request, *args, **kwargs)
        paper_event_id = res.data['id']
        if created_location == PaperEvent.PAPER and PaperEvent.VIEW:
            create_contribution.apply_async(
                (
                    Contribution.SUPPORTER,
                    {'app_label': 'analytics', 'model': 'paperevent'},
                    user.id,
                    paper_id,
                    paper_event_id
                ),
                priority=2,
                countdown=10
            )

    @action(
        detail=False,
        methods=['POST'],
        permission_classes=[]
    )
    def batch_views(self, request, *args, **kwargs):
        user = request.user
        if not user.is_anonymous:
            request.data['user'] = user

        created_location = request.data.get('created_location')
        if created_location is not None:
            created_location = created_location.upper()
            request.data['created_location'] = created_location
        else:
            return Response(
                'Missing required field `created_location`',
                status=status.HTTP_400_BAD_REQUEST
            )

        interaction = request.data.get('interaction', None)
        if interaction is not None:
            interaction = interaction.upper()
            request.data['interaction'] = interaction

        events = []
        paper_ids = request.data['paper_ids']
        del request.data['paper_ids']
        for id in paper_ids:
            events.append(PaperEvent(paper_id=id, **request.data))

        PaperEvent.objects.bulk_create(events)
        return Response({'msg': 'Events Created'}, 201)


class AmplitudeViewSet(viewsets.ViewSet):
    authentication_classes = ()

    def get_permissions(self):
        return [AllowAny()]

    def create(self, request, *args, **kwargs):
        data = request.data
        amp = Amplitude()
        amp.build_hit(request, data)
        amp.forward_event()
        return Response(status=200)
