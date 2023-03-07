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

    def create_from_request(self):
        # TODO: calvinhlee - add validations on the payload
        request = self.context.get("request")
        request_data = request.data
        rh_thread = self._retrieve_or_create_thread_from_request()
        [
            comment_content_src_file,
            comment_content_type,
        ] = self._get_comment_src_file_from_request()
        rh_comment = RhCommentModel.object.create(
            thread=rh_thread,
            parent=request_data.get("parent_id"),
            comment_content_type=comment_content_type,
        )
        rh_comment.comment_content_src.save(
            f"RH-THREAD-{rh_thread.id}-COMMENT-{rh_comment.id}-user-{request.user.id}.txt",
            comment_content_src_file,
        )
