from django.db.models import CharField

from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT, RH_COMMENT_THREAD_TYPES
from utils.models import AbstractGenericRelationModel


class RhCommentThreadModel(AbstractGenericRelationModel):
    thread_type = CharField(
        max_length=144,
        choices=RH_COMMENT_THREAD_TYPES,
        default=GENERIC_COMMENT,
    )
