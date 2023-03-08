from django.db.models import CharField

from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT, RH_COMMENT_THREAD_TYPES
from utils.models import AbstractGenericRelationModel


"""
    NOTE: RhCommentThreadModel's generic relation convention is to
        - dealth with AbstractGenericRelationModel
        - SHOULD add to target content_model an edge named `rh_threads` (see Paper Model for example)
        - this allows ContentModel.rh_threads[...] queries and allows usage of _get_valid_thread_content_model 
            (see _get_valid_thread_content_model in RhThreadSerializer)
"""

class RhCommentThreadModel(AbstractGenericRelationModel):
    """ --- MODEL FIELDS --- """
    thread_type = CharField(
        max_length=144,
        choices=RH_COMMENT_THREAD_TYPES,
        default=GENERIC_COMMENT,
    )
    thread_reference = CharField(
        blank=True,
        help_text="""A thread may need a special referencing tool. Use this field for such a case""",
        max_length=144,
        null=True,
    )

    """ --- METHODS --- """
    @classmethod
    def get_existing_thread_from_request(cls, request):
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
            valid_content_model = cls.get_valid_thread_content_model(
                thread_content_model_name
            )
            return valid_content_model.object.get(
                id=thread_content_instance_id
            ).rh_threads.filter(
                thread_reference=thread_reference, thread_type=thread_type
            ).first()

    @staticmethod
    def get_valid_thread_content_model(thread_content_model_name):
        from paper.models import Paper

        if thread_content_model_name == "paper":
            return Paper
        else:
            raise Exception(
                f"Failed get_valid_thread_content_model:. \
                  invalid thread_content_model_name: {thread_content_model_name}"
            )
