from researchhub_comment.models import RhCommentModel
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.viewsets import ModelViewSet
from requests import Response
from rest_framework import status

from researchhub_comment.serializers.rh_comment_serializer import RhCommentSerializer
from researchhub_comment.models import RhCommentThreadModel


class RhCommentViewSet(ModelViewSet):
    queryset = RhCommentModel.objects.filter()
    serializer_class = RhCommentSerializer
    permission_classes = [
        # IsAuthenticatedOrReadOnly,
        AllowAny,  # TODO: calvinhlee replace with above permissions
    ]

    def create(self, request, *args, **kwargs):
        return Response(
            "Creating RhComment with direct view is prohibited",
            status=status.HTTP_400_BAD_REQUEST,
        )

    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)