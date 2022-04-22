from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from user.models import UserApiToken
from user.permissions import CreateOrViewOrRevokeUserApiToken
from user.serializers import UserApiTokenSerializer
from utils.http import DELETE
from utils.throttles import THROTTLE_CLASSES


class UserApiTokenViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated, CreateOrViewOrRevokeUserApiToken]
    queryset = UserApiToken.objects.all()
    serializer_class = UserApiTokenSerializer
    throttle_classes = THROTTLE_CLASSES
    lookup_value_regex = r"[aA-zZ0-9]+\.[aA-zZ0-9]+"

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        return qs.filter(user=user, revoked=False)

    def create(self, request):
        user = request.user
        data = request.data

        name = data.get("name", "")
        _, token = UserApiToken.objects.create_key(name=name, user=user)
        return Response({"token": token}, status=201)

    def destroy(self, request, pk=None):
        api_token = UserApiToken.objects.get_from_key(pk)
        api_token.revoked = True
        api_token.save()
        serializer = self.get_serializer(api_token)
        return Response(serializer.data, status=200)

    @action(detail=False, methods=[DELETE])
    def revoke_token(self, request):
        filters = {}
        data = request.data

        if "name" in data:
            filters["name"] = data.get("name")
        if "prefix" in data:
            filters["prefix"] = data.get("prefix")

        tokens = self.get_queryset().filter(**filters)
        tokens.update(revoked=True)
        return Response({"data": "Revoked"}, status=200)
