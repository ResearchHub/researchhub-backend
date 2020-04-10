from django.shortcuts import render
from .models import WebsiteVisits
from .serializers import WebsiteVisitsSerializer

class WebsiteVisitsViewSet(viewsets.ModelViewSet):
    queryset = WebsiteVisits.objects.all()
    serializer_class = WebsiteVisitSerializer
    http_method_names = ['post']
