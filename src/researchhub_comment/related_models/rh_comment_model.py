from django.db.models import CharField, FileField, TextField, ForeignKey, CASCADE, DateTimeField

from discussion.reaction_models import AbstractGenericReactionModel
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR, RH_COMMENT_CONTENT_TYPES
from researchhub_comment.related_models.rh_comment_thread_model import RhCommentThreadModel


class RhCommentModel(AbstractGenericReactionModel):
    # auth
    created_by = ForeignKey(
        "user.User",
        auto_created=True,
        on_delete=CASCADE,
        related_name="created_rh_comments",
    )
    updated_by = ForeignKey(
        "user.User",
        auto_created=True,
        on_delete=CASCADE,
        related_name="updated_rh_comments",
    )

    # comments
    context_title = TextField(
        blank=True,
        null=True,
        help_text="""
            Provides a sumamry / headline to give context to the comment. 
            A commont use-case for this is for inline comments & citation comments
        """,
    )
    comment_content_src = FileField(
        blank=True,
        max_length=1024,
        upload_to="uploads/rh_comment/%Y/%m/%d/",
        help_text="""Src may be blank but never null upon saving."""
    )
    comment_content_type = CharField(
        choices=RH_COMMENT_CONTENT_TYPES,
        default=QUILL_EDITOR,
        max_length=144,
    )
    thread = ForeignKey(
        RhCommentThreadModel,
        db_index=True,
        on_delete=CASCADE,
        related_name="rh_comments",
    )
