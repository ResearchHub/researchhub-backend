from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated

from researchhub_case.models import AuthorClaimCase
from researchhub_case.serializers import AuthorClaimCaseSerializer
from utils.http import GET


class GatekeeperViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    queryset = AuthorClaimCase.objects.all().order_by("-created_date")
    serializer_class = AuthorClaimCaseSerializer


    @action(
        detail=True,
        methods=[GET],
        permission_classes=[
            CreateOrUpdateIfAllowed
        ]
    )
    def check_email(self, request, pk=None):
        item = self.get_object()
        user = request.user

        # vote_exists = find_vote(user, item, Vote.UPVOTE)

        return Response(
            'This vote already exists',
            status=status.HTTP_400_BAD_REQUEST
        )
        # if vote_exists:
        # response = update_or_create_vote(request, user, item, Vote.UPVOTE)
        # return response