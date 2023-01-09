from django.db.models import CharField, TextField

from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR, RH_COMMENT_CONTENT_TYPES
from discussion.reaction_models import AbstractGenericReactionModel
from utils.models import DefaultAuthenticatedModel

class RhCommentModel(AbstractGenericReactionModel, DefaultAuthenticatedModel):
    context_title = TextField(
        blank=True,
        null=True,
        help_text="""
            Provides a sumamry / headline to give context to the comment. 
            A commont use-case for this is for inline comments & citation comments
        """,
    )
    comment_content_type = CharField(
        choices=RH_COMMENT_CONTENT_TYPES,
        default=QUILL_EDITOR,
        max_length=144,
    )
