from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from .models import Hub
from .permissions import CreateHub
from .serializers import HubSerializer


class HubViewSet(viewsets.ModelViewSet):
    queryset = Hub.objects.all()
    serializer_class = HubSerializer

    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    permission_classes = [IsAuthenticatedOrReadOnly & CreateHub]
    search_fields = ('name')
