from requests import Response
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.viewsets import ModelViewSet

from researchhub_comment.serializers.rh_comment_thread_serializer import (
    RhCommentThreadSerializer,
)
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel


class RhCommentThreadViewSet(ModelViewSet):
    queryset = RhCommentThreadModel.objects.filter()
    serializer_class = RhCommentThreadSerializer
    permission_classes = [
        # IsAuthenticatedOrReadOnly,
        AllowAny,  # TODO: calvinhlee replace with above permissions
    ]

    def create(self, request, *args, **kwargs):
        return Response(
            "Creating RhCommentThread with direct view is prohibited. Use /create_comment",
            status=status.HTTP_400_BAD_REQUEST,
        )

    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=["POST"], permission_classes=[IsAuthenticated])
    def create_comment(self, request, pk=None):
        try:
            rh_thread = self._retrieve_or_create_thread_from_request()
            _rh_comment = RhCommentModel.create_from_request(request, rh_thread)
            rh_thread.refresh_from_db()  # object update from fresh db_values

            return Response(self.get_serializer(instance=rh_thread).data, status=200)
        except Exception as error:
            return Response(
                f"Failed - create_comment: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _retrieve_or_create_thread_from_request(self):
        try:
            request = self.context.get("request")
            request_data = request.data
            thread_id = request_data.get("thread_id")
            if thread_id:
                return RhCommentThreadModel.obejcts.get(thread_id)
            else:
                existing_thread = (
                    RhCommentThreadSerializer._get_existing_thread_from_request(request)
                )
                if existing_thread is not None:
                    return existing_thread
                else:
                    valid_content_model = (
                        RhCommentThreadModel.get_valid_thread_content_model(
                            request_data.get("content_model_name")
                        )
                    )
                    thread_content_instance = valid_content_model.objects.get(
                        id=request_data.get("content_model_instance_id")
                    )
                    return thread_content_instance.rh_threads.create(
                        thread_type=request_data.get("thread_type"),
                        thread_reference=request_data.get("thread_reference"),
                    )
        except Exception as error:
            return Response(
                f"Failed to create / retrieve rh_thread: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )
