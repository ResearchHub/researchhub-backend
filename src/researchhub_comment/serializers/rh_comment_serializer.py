from requests import Response
from rest_framework import status, viewsets

from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)


class RhCommentSerializer(viewsets.ModelViewSet):
    def __retrieve_or_create_thread_from_request(self):
        try:
            request = self.context.get("request")
            request_data = request.data
            thread_id = request_data.get("thread_id")
            if thread_id:
                return RhCommentThreadModel.obejcts.get(thread_id)
            else:
                thread_type = request_data.get("thread_type")
                thread_reference = request_data.get("thread_reference")
                thread_target_model = request_data.get("thread_target_model")
                thread_target_model_instance_id = request_data.get("thread_target_model_instance_id")
                if thread_type is None or thread_target_model is None or thread_target_model_instance_id is None:
                    raise Exception(
                        f"Failed to call __retrieve_or_create_thread_from_request. \
                          thread_type: {thread_type} | thread_target_model: {thread_target_model} |\
                          thread_target_model_instance_id: {thread_target_model_instance_id}"
                    )
                else:
                    content_object = 123  # TODO: calvinhlee look up docs to retrive this
                    retrieved_thread = RhCommentThreadModel.object.filter(
                        thread_type=thread_type,
                        thread_reference=thread_reference,
                    ).first()
        except Exception as error:
            return Response(
                f"Failed to create endorsement: {error}",
                status=status.HTTP_400_BAD_REQUEST,
            )
