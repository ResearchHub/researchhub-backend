from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from user.permissions import IsModerator, UserIsEditor
from user.serializers import ModeratorUserSerializer


class ModeratorView(ModelViewSet):

    @action(
        detail=True, methods=["get"], permission_classes=[UserIsEditor | IsModerator]
    )
    def user_details(self, request, pk=None, **kwargs):
        from user.models import User

        user = User.objects.get(id=pk)
        serializer = ModeratorUserSerializer(user)

        return Response(serializer.data)
