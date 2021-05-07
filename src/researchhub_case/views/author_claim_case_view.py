from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer


class AuthorClaimCaseViewSet(viewsets.ModelViewSet):
    permission_classes = [
        # TODO: calvinhlee - add more privacy later
        AllowAny
    ]
    queryset = AuthorClaimCase.objects.all()
    serializer_class = AuthorClaimCaseSerializer
