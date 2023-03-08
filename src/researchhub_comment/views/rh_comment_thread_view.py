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
            "Directly creating RhCommentThread with view is prohibited. Use /create_comment",
            status=status.HTTP_400_BAD_REQUEST,
        )

    def retrieve(self, request, *args, **kwargs):
        # TODO - calvinhlee - update to reflect content id & thread types & sortable params
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=["POST"], permission_classes=[IsAuthenticated])
    def create_comment(self, request, pk=None):
        try:
            rh_thread = self._retrieve_or_create_thread_from_request_data(request.data)
            _rh_comment = RhCommentModel.create_from_request(request, rh_thread)
            rh_thread.refresh_from_db()  # object update from fresh db_values

            return Response(self.get_serializer(instance=rh_thread).data, status=200)
        except Exception as error:
            return Response(
                f"Failed - create_comment: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _retrieve_or_create_thread_from_request_data(self, request_data):
        try:
            thread_id = request_data.get("thread_id")
            if thread_id:
                return RhCommentThreadModel.obejcts.get(thread_id)
            else:
                existing_thread = self._get_existing_thread_from_request_data(request_data)
                if existing_thread is not None:
                    return existing_thread
                else:
                    valid_thread_target_model = (
                        RhCommentThreadModel.get_valid_thread_target_model(
                            request_data.get("thread_target_model_name")
                        )
                    )
                    thread_target_instance = valid_thread_target_model.objects.get(
                        id=request_data.get("thread_target_model_instance_id")
                    )
                    return thread_target_instance.rh_threads.create(
                        thread_type=request_data.get("thread_type"),
                        thread_reference=request_data.get("thread_reference"),
                    )
        except Exception as error:
            raise Exception(f"Failed to create / retrieve rh_thread: {error}")

    def _get_existing_thread_from_request_data(self, request_data):
        thread_id = request_data.get("thread_id")
        if thread_id is not None:
            return RhCommentThreadModel.objects.get(id=thread_id)

        thread_target_model_instance_id = request_data.get(
            "thread_target_model_instance_id"
        )
        thread_target_model_name = request_data.get("thread_target_model_name")
        thread_reference = request_data.get("thread_reference")
        thread_type = request_data.get("thread_type")
        if (
            thread_type is None
            or thread_target_model_name is None
            or thread_target_model_instance_id is None
        ):
            raise Exception(
                f"Failed to call __retrieve_or_create_thread_from_request_data. \
                thread_type: {thread_type} | thread_target_model_name: {thread_target_model_name} |\
                thread_target_model_instance_id: {thread_target_model_instance_id}"
            )
        else:
            valid_thread_target_model = (
                RhCommentThreadModel.get_valid_thread_target_model(
                    thread_target_model_name
                )
            )
            return (
                valid_thread_target_model.object.get(id=thread_target_model_instance_id)
                .rh_threads.filter(
                    thread_reference=thread_reference, thread_type=thread_type
                )
                .first()
            )
