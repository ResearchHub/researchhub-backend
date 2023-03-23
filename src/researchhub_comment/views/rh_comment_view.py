from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status
from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from discussion.reaction_views import ReactionViewActionMixin
from researchhub_comment.filters import RHCommentFilter
from researchhub_comment.models import RhCommentModel
from researchhub_comment.serializers import RhCommentSerializer
from researchhub_comment.views.rh_comment_view_mixin import RhCommentViewMixin


class CursorSetPagination(CursorPagination):
    page_size = 20
    cursor_query_param = "page"
    ordering = "-created_date"


class CommentPagination(PageNumberPagination):
    max_page_size = 20
    page_size = 20


class RhCommentViewSet(ReactionViewActionMixin, RhCommentViewMixin, ModelViewSet):
    queryset = RhCommentModel.objects.all()
    serializer_class = RhCommentSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = RHCommentFilter
    pagination_class = CommentPagination
    permission_classes = [
        # IsAuthenticatedOrReadOnly,
        AllowAny,  # TODO: calvinhlee replace with above permissions
    ]

    def create(self, request, *args, **kwargs):
        return Response(
            "Directly creating RhComment with view is prohibited. Use /rh_comment_thread/create_comment",
            status=status.HTTP_400_BAD_REQUEST,
        )
