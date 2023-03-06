from researchhub_comment.models import RhCommentModel
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.viewsets import ModelViewSet

from researchhub_comment.serializers.rh_comment_serializer import RhCommentSerializer


class RhCommentViewSet(ModelViewSet):
    queryset = RhCommentModel.objects.filter()
    serializer_class = RhCommentSerializer
    permission_classes = [
        # IsAuthenticatedOrReadOnly,
        AllowAny,  # TODO: calvinhlee replace with above permissions
    ]

    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)