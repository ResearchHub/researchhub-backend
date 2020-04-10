from django.shortcuts import render
from .models import WebsiteVisits
from .serializers import WebsiteVisitsSerializer
from rest_framework import viewsets

class WebsiteVisitsViewSet(viewsets.ModelViewSet):
    queryset = WebsiteVisits.objects.all()
    serializer_class = WebsiteVisitsSerializer
    http_method_names = ['post']
    permission_classes = ()
