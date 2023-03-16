from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from discussion.reaction_views import ReactionViewActionMixin
from researchhub_comment.models import RhCommentModel
from researchhub_comment.serializers import RhCommentSerializer
from researchhub_comment.views.rh_comment_thread_view_mixin import (
    RhCommentThreadViewMixin,
)


class RhCommentViewSet(ReactionViewActionMixin, RhCommentThreadViewMixin, ModelViewSet):
    queryset = RhCommentModel.objects.filter()
    serializer_class = RhCommentSerializer
    permission_classes = [
        # IsAuthenticatedOrReadOnly,
        AllowAny,  # TODO: calvinhlee replace with above permissions
    ]

    def create(self, request, *args, **kwargs):
        return Response(
            "Directly creating RhComment with view is prohibited. Use /rh_comment_thread/create_comment",
            status=status.HTTP_400_BAD_REQUEST,
        )
