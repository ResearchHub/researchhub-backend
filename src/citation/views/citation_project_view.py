from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.viewsets import ModelViewSet

from citation.models import CitationProject
from citation.serializers import CitationProjectSerializer


class CitationProjectViewSet(ModelViewSet):
    queryset = CitationProject.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = CitationProjectSerializer
    ordering = ["-updated_date"]
