from django.db.models import CharField

from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
)
from utils.models import AbstractGenericRelationModel

"""
    NOTE: RhCommentThreadModel's generic relation convention is to
        - setup relations through AbstractGenericRelationModel
        - add an edge named `rh_threads` for inverse reference (see Paper Model for example)

    This allows queries such as [ContentModel].rh_threads[...]
    where [ContentModels] may be found in method "get_valid_target_content_model"
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

    """ --- PROPERTIES --- """
    # TBD

    """--- METHODS ---"""

    @staticmethod
    def get_valid_target_content_model(thread_content_model_name):
        from hypothesis.related_models.citation import Citation
        from hypothesis.related_models.hypothesis import Hypothesis
        from paper.models import Paper
        from researchhub_document.models import (
            ResearchhubPost,
        )

        if thread_content_model_name == "citation":
            return Citation
        elif thread_content_model_name == "hypothesis":
            return Hypothesis
        elif thread_content_model_name == "paper":
            return Paper
        elif thread_content_model_name == "researchhub_post":
            return ResearchhubPost
        else:
            raise Exception(
                f"Failed get_valid_target_content_model:. \
                  invalid thread_content_model_name: {thread_content_model_name}"
            )
