from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from user.models import UserApiToken
from user.permissions import CreateOrRevokeUserApiToken
from user.serializers import UserApiTokenSerializer


class UserApiTokenViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated, CreateOrRevokeUserApiToken]
    queryset = UserApiToken.objects.all()
    serializer_class = UserApiTokenSerializer
    lookup_value_regex = r"[aA-zZ0-9]+\.[aA-zZ0-9]+"

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
        return Response({"data": "revoked"}, status=200)
