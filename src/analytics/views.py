from rest_framework import status, viewsets
from rest_framework.response import Response

from analytics.models import PaperEvent, WebsiteVisits
from analytics.permissions import UpdateOrDelete
from analytics.serializers import (
    PaperEventSerializer,
    WebsiteVisitsSerializer
)


class WebsiteVisitsViewSet(viewsets.ModelViewSet):
    queryset = WebsiteVisits.objects.all()
    serializer_class = WebsiteVisitsSerializer
    http_method_names = ['post']
    permission_classes = ()


class PaperEventViewSet(viewsets.ModelViewSet):
    queryset = PaperEvent.objects.all()
    serializer_class = PaperEventSerializer
    permission_classes = [UpdateOrDelete]

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
        return super().create(request, *args, **kwargs)
