from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from .models import Paper
from .serializers import PaperSerializer


class PaperViewSet(viewsets.ModelViewSet):
    queryset = Paper.objects.all()
    serializer_class = PaperSerializer

    # Optional attributes
    permission_classes = [IsAuthenticatedOrReadOnly]
