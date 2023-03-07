from django.db.models import CharField

from paper.models import Paper
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
    @staticmethod
    def get_valid_thread_content_model(thread_content_model_name):
        if thread_content_model_name == "paper":
            return Paper
        else:
            raise Exception(
                f"Failed get_valid_thread_content_model:. \
                  invalid thread_content_model_name: {thread_content_model_name}"
            )
