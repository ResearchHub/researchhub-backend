from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from citation.models import CitationEntry
from citation.serializers import CitationSerializer


class CitationViewSet(ModelViewSet):
    queryset = CitationEntry.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = CitationSerializer
