from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from rest_framework.permissions import IsAuthenticated
from user.related_models.gatekeeper_model import Gatekeeper

from utils.http import GET


class GatekeeperViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Gatekeeper.objects.all()
    # serializer_class = GatekeeperSerializer -> no need for it yet

    @action(
        detail=True,
        methods=[GET],
        permission_classes=[IsAuthenticated]
    )
    def check_email(self, request, pk=None):
        curr_user = request.user
        gatekeeper_type = request.data.get('type')
        vote_exists = Gatekeeper.objects.filter(
          email=curr_user.email,
          type=gatekeeper_type
        ).exists()

        if (vote_exists):
            return Response(True, status=status.HTTP_200_OK)

        return Response(
            'Cannot find given user & type',
            status=status.HTTP_404_NOT_FOUND
        )
