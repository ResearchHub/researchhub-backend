from django.db.models import CASCADE, CharField, DateTimeField, ForeignKey

from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT, RH_COMMENT_THREAD_TYPES
from utils.models import AbstractGenericRelationModel, DefaultAuthenticatedModel


class RhCommentThreadModel(AbstractGenericRelationModel):
    thread_type = CharField(
        max_length=144,
        choices=RH_COMMENT_THREAD_TYPES,
        default=GENERIC_COMMENT,
    )
    thread_reference = CharField(
        blank=True,
        help_text="""A thread may need a spcial referencing tool. Use this field for such a case""",
        max_length=144,
        null=True,
    )
