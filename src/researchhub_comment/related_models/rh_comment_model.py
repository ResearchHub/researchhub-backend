from django.db.models import (
    CASCADE,
    CharField,
    FileField,
    ForeignKey,
    PositiveIntegerField,
    SET_NULL,
    TextField,
)

from discussion.reaction_models import AbstractGenericReactionModel
from researchhub_comment.constants.rh_comment_content_types import QUILL_EDITOR, RH_COMMENT_CONTENT_TYPES
from researchhub_comment.constants.rh_comment_migration_legacy_types import (
    LEGACY_COMMENT, RH_COMMENT_MIGRATION_LEGACY_TYPES
)
from researchhub_comment.related_models.rh_comment_thread_model import RhCommentThreadModel
from utils.models import DefaultAuthenticatedModel


class RhCommentModel(AbstractGenericReactionModel, DefaultAuthenticatedModel):
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
    parent = ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=SET_NULL,
        related_name="responses",
    )
    thread = ForeignKey(
        RhCommentThreadModel,
        db_index=True,
        on_delete=CASCADE,
        related_name="rh_comments",
    )

    # legacy_migration
    legacy_id = PositiveIntegerField
    legacy_model_type = CharField(
        choices=RH_COMMENT_MIGRATION_LEGACY_TYPES,
        default=LEGACY_COMMENT,
        max_length=144,
    )
