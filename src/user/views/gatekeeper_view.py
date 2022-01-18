from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from rest_framework.permissions import AllowAny
from user.related_models.gatekeeper_model import Gatekeeper
from user.serializers import GatekeeperSerializer

from utils.http import GET


class GatekeeperViewSet(ModelViewSet):
    permission_classes = [AllowAny]
    queryset = Gatekeeper.objects.all()
    serializer_class = GatekeeperSerializer

    @action(
        detail=False,
        methods=[GET],
        permission_classes=[AllowAny]
    )
    def check_current_user(self, request, pk=None):
        curr_user = request.user

        if curr_user.is_anonymous:
            return Response(status=403)

        gatekeeper_type = request.query_params.get('type')
        vote_exists = Gatekeeper.objects.filter(
          email=curr_user.email,
          type=gatekeeper_type
        ).exists()

        if vote_exists:
            return Response(True, status=status.HTTP_200_OK)

        return Response(
            {'data': 'Cannot find given user & type'},
            status=status.HTTP_404_NOT_FOUND
        )
