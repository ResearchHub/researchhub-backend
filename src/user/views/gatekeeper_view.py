from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from hub.permissions import IsModerator
from user.models.gatekeeper_model import Gatekeeper
from user.serializers import GatekeeperSerializer
from utils.http import GET


class GatekeeperViewSet(ModelViewSet):
    permission_classes = [IsModerator]
    queryset = Gatekeeper.objects.all()
    serializer_class = GatekeeperSerializer

    @action(detail=False, methods=[GET], permission_classes=[AllowAny])
    def check_current_user(self, request, pk=None):
        curr_user = request.user

        if curr_user.is_anonymous:
            return Response(status=403)

        gatekeeper_type = request.query_params.get("type")
        exists = Gatekeeper.objects.filter(
            Q(email=curr_user.email) | Q(user=curr_user), type=gatekeeper_type
        ).exists()

        if exists:
            return Response(True, status=status.HTTP_200_OK)

        return Response(
            {"data": "User not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED
        )
