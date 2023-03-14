from django.db import transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_comment.serializers import (
    DynamicRHThreadSerializer,
    RhCommentThreadSerializer,
)


class RhCommentThreadViewMixin:
    def _get_retrieve_context(self):
        context = {
            "rhc_dts_get_comments": {"_include_fields": ("id", "created_by")},
            "rhc_dcs_get_created_by": {
                "_include_fields": (
                    "id",
                    "author_profile",
                )
            },
            "usr_dus_get_author_profile": {
                "_include_fields": (
                    "id",
                    "first_name",
                    "last_name",
                    "created_date",
                    "updated_date",
                    "profile_image",
                )
            },
        }
        return context

    @action(detail=True, methods=["POST"], permission_classes=[IsAuthenticated])
    def create_rh_comment(self, request, pk=None):
        try:
            rh_thread = self._retrieve_or_create_thread_from_request(request)
            _rh_comment = RhCommentModel.create_from_data(
                {**request.data, "user": request.user}, rh_thread
            )
            rh_thread.refresh_from_db()  # object update from fresh db values
            return Response(
                RhCommentThreadSerializer(instance=rh_thread).data, status=200
            )
        except Exception as error:
            return Response(
                f"Failed - create_rh_comment: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )

    # @action(detail=True, methods=["GET"], permission_classes=[AllowAny], url_path=r"(?P<model>\w+)")
    @action(
        detail=True, methods=["GET"], permission_classes=[AllowAny], url_path=r"blah"
    )
    def get_rh_comments(self, request, pk=None):
        try:
            # TODO: add filtering & sorting mechanism here.
            context = self._get_retrieve_context()
            rh_thread = self._get_existing_thread_from_request(request)
            serializer = DynamicRHThreadSerializer(
                rh_thread,
                context=context,
                _include_fields=("id", "comments"),
            )
            return Response(serializer.data, status=200)
        except Exception as error:
            return Response(
                f"Failed - get_comment_threads: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _retrieve_or_create_thread_from_request(self, request):
        request_data = request.data
        try:
            thread_id = request_data.get("thread_id") or None
            if thread_id is not None:
                return RhCommentThreadModel.objects.get(id=thread_id)
            else:
                existing_thread = self._get_existing_thread_from_request(request)
                if existing_thread is not None:
                    return existing_thread
                else:
                    valid_thread_target_model = (
                        RhCommentThreadModel.get_valid_thread_target_model(
                            self._resolve_target_model_name(request)
                        )
                    )
                    thread_target_instance = valid_thread_target_model.objects.get(
                        id=self._resolve_target_model_instance_id(request)
                    )
                    return thread_target_instance.rh_threads.create(
                        thread_type=request_data.get("thread_type"),
                        thread_reference=request_data.get("thread_reference"),
                    )
        except Exception as error:
            raise Exception(f"Failed to create / retrieve rh_thread: {error}")

    def _get_existing_thread_from_request(self, request):
        request_data = request.data
        """ NOTE: sanity checking if payload included thread_id """
        thread_id = request_data.get("thread_id") or None
        if thread_id is not None:
            return RhCommentThreadModel.objects.get(id=thread_id)

        """ ---- Attempting to resolve payload ---- """
        thread_reference = request_data.get("thread_reference")
        thread_type = request_data.get("thread_type") or GENERIC_COMMENT
        thread_target_model_instance_id = self._resolve_target_model_instance_id(
            request
        )
        thread_target_model_name = self._resolve_target_model_name(request)

        if (
            thread_type is None
            or thread_target_model_name is None
            or thread_target_model_instance_id is None
        ):
            raise Exception(
                f"Failed to call __retrieve_or_create_thread_from_request. \
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
                valid_thread_target_model.objects.get(
                    id=thread_target_model_instance_id
                )
                .rh_threads.filter(
                    thread_reference=thread_reference, thread_type=thread_type
                )
                .first()
            )

    def _resolve_target_model_instance_id(self, request):
        thread_target_model_instance_id = (
            request.data.get("thread_target_model_instance_id") or None
        )
        return (
            thread_target_model_instance_id
            if thread_target_model_instance_id is not None
            else self._get_model_instance_id_from_request(request)
        )

    def _resolve_target_model_name(self, request):
        thread_target_model_name = (
            request.data.get("thread_target_model_instance_id") or None
        )
        return (
            thread_target_model_name
            if thread_target_model_name is not None
            else self._get_model_name_from_request(request)
        )

    def _get_model_name_from_request(self, request):
        return request.path.split("/")[2]

    def _get_model_instance_id_from_request(self, request):
        return int(request.path.split("/")[3])
