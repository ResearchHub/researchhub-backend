from django.db.models import CharField

from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
)
from utils.models import AbstractGenericRelationModel

"""
    NOTE: RhCommentThreadModel's generic relation convention is to
        - setup relations through AbstractGenericRelationModel
        - add an edge named `rh_threads` for inverse reference on top of a target [content] model
        - (see Hypothesis Model for reference)

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
    def get_valid_thread_target_model(thread_target_model_name):
        # importing within this method prevents cyclical import
        from hypothesis.models import Citation, Hypothesis
        from paper.models import Paper
        from researchhub_document.models import ResearchhubPost

        if thread_target_model_name == "citation":
            return Citation
        elif thread_target_model_name == "hypothesis":
            return Hypothesis
        elif thread_target_model_name == "paper":
            return Paper
        elif thread_target_model_name == "researchhub_post":
            return ResearchhubPost
        else:
            import pdb; pdb.set_trace()
            raise Exception(
                f"Failed get_valid_target_content_model: invalid thread_target_model_name: {thread_target_model_name}"
            )
