from rest_framework import viewsets
from paper.models import Paper


class RhThreadSerializer(viewsets.ModelViewSet):
    def _get_existing_thread_from_request(request):
        request_data = request.data
        thread_type = request_data.get("thread_type")
        thread_reference = request_data.get("thread_reference")
        thread_content_model_name = request_data.get("thread_content_model_name")
        thread_content_instance_id = request_data.get("thread_content_instance_id")
        if (
            thread_type is None
            or thread_content_model_name is None
            or thread_content_instance_id is None
        ):
            raise Exception(
                f"Failed to call __retrieve_or_create_thread_from_request. \
                  thread_type: {thread_type} | thread_content_model_name: {thread_content_model_name} |\
                  thread_content_instance_id: {thread_content_instance_id}"
            )
        else:
            valid_content_model = RhThreadSerializer._get_valid_thread_content_model(
                thread_content_model_name
            )
            return valid_content_model.object.get(
                id=thread_content_instance_id
            ).rh_threads.filter(
                thread_reference=thread_reference, thread_type=thread_type
            ).first()

    def _get_valid_thread_content_model(thread_content_model_name):
        if thread_content_model_name == "paper":
            return Paper
        else:
            raise Exception(
                f"Failed _get_valid_thread_content_model:. \
                  invalid thread_content_model_name: {thread_content_model_name}"
            )
