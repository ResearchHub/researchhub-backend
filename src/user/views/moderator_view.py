from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet

from user.models import User
from user.permissions import IsModerator, UserIsEditor
from user.serializers import ModeratorUserSerializer


class ModeratorView(ModelViewSet):
    queryset = User.objects.select_related(
        "userverification",
    )
    serializer_class = ModeratorUserSerializer
    permission_classes = [UserIsEditor | IsModerator]

    @action(
        detail=True, methods=["get"], permission_classes=[UserIsEditor | IsModerator]
    )
    def user_details(self, request, pk=None, **kwargs):
        return super().retrieve(request, pk, **kwargs)
