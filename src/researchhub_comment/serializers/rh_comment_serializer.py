from requests import Response
from rest_framework import status, viewsets
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_comment.serializers.rh_thread_serializer import RhThreadSerializer
from django.core.files.base import ContentFile


class RhCommentSerializer(viewsets.ModelViewSet):
    def create(self):
        # TODO: calvinhlee - add validations on the payload
        request = self.context.get("request")
        request_data = request.data
        rh_thread = self._retrieve_or_create_thread_from_request()
        [comment_content_src_file, comment_content_type] = self._get_comment_src_file_from_request()
        rh_comment = RhCommentModel.object.create(
            thread=rh_thread,
            parent=request_data.get("parent_id"),
            comment_content_type=comment_content_type
        )
        rh_comment.comment_content_src.save(
            f"RH-THREAD-{rh_thread.id}-COMMENT-{rh_comment.id}-user-{request.user.id}.txt",
            comment_content_src_file,
        )

    def _get_comment_src_file_from_request(self):
        try:
            request_data = self.context.get("request").data
            comment_content = request_data.get("comment_content")
            if (comment_content is None):
                raise Exception(
                    "Failed to comment content should not be None when creating a comment"
                )

            comment_content_src_file = ContentFile(comment_content.encode())
            return [comment_content_src_file, request_data.get("comment_content_type")]
        except Exception as error:
            return Response(
                f"Failed to create endorsement: {error}",
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
                existing_thread = RhThreadSerializer._get_existing_thread_from_request(request)
                if existing_thread is not None:
                    return existing_thread
                else:
                    thread_content_model_name = request_data.get("thread_content_model_name")
                    valid_content_model = RhThreadSerializer._get_valid_thread_content_model(
                        thread_content_model_name
                    )
                    thread_content_instance = valid_content_model.objects.get(
                        id=request_data.get("thread_content_instance_id")
                    )
                    return thread_content_instance.rh_threads.create(
                        thread_type=request_data.get("thread_type"),
                        thread_reference=request_data.get("thread_reference")
                    )
        except Exception as error:
            return Response(
                f"Failed to create endorsement: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )
