from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend, FilterSet

from .models import Paper
from .serializers import PaperSerializer
from reputation.permissions import CreatePaper


class PaperViewSet(viewsets.ModelViewSet):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer
    filter_backends = (SearchFilter, DjangoFilterBackend, OrderingFilter)
    search_fields = ('title', 'doi')

    # Optional attributes
    permission_classes = [IsAuthenticatedOrReadOnly & CreatePaper]
