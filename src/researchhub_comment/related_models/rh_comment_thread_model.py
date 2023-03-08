from django.db.models import CharField

from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
)
from utils.models import AbstractGenericRelationModel

"""
    NOTE: RhCommentThreadModel's generic relation convention is to
        - dealth with AbstractGenericRelationModel
        - SHOULD add to target content_model an edge named `rh_threads` (see Paper Model for example)
        - this allows ContentModel.rh_threads[...] queries and allows usage of _get_valid_target_content_model
"""


class RhCommentThreadModel(AbstractGenericRelationModel):
    """--- MODEL FIELDS ---"""

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

    @staticmethod
    def get_valid_target_content_model(thread_content_model_name):
        from paper.models import Paper
        from researchhub_document.models import (
            ResearchhubPost,
        )

        if thread_content_model_name == "paper":
            return Paper
        if thread_content_model_name == "researchhub_post":
            return ResearchhubPost
        else:
            raise Exception(
                f"Failed get_valid_target_content_model:. \
                  invalid thread_content_model_name: {thread_content_model_name}"
            )
