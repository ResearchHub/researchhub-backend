from rest_framework import viewsets

from analytics.models import WebsiteVisits
from analytics.serializers import WebsiteVisitsSerializer


class WebsiteVisitsViewSet(viewsets.ModelViewSet):
    queryset = WebsiteVisits.objects.all()
    serializer_class = WebsiteVisitsSerializer
    http_method_names = ["post"]
    permission_classes = ()
