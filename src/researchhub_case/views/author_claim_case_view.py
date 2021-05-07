from rest_framework import viewsets
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly
)

from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer


class AuthorClaimCaseViewSet(viewsets.ModelViewSet):
    permission_classes = [
       AllowAny
    ]
    queryset = AuthorClaimCase.objects.all()
    serializer_class = AuthorClaimCaseSerializer
    # permission_classes = [IsAuthenticatedOrReadOnly]
