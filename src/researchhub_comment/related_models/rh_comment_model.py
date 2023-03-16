import json

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import (
    CASCADE,
    SET_NULL,
    BooleanField,
    CharField,
    FileField,
    ForeignKey,
    JSONField,
    PositiveIntegerField,
    TextField,
)

from discussion.reaction_models import AbstractGenericReactionModel
from researchhub_comment.constants.rh_comment_content_types import (
    QUILL_EDITOR,
    RH_COMMENT_CONTENT_TYPES,
)
from researchhub_comment.constants.rh_comment_migration_legacy_types import (
    LEGACY_COMMENT,
    RH_COMMENT_MIGRATION_LEGACY_TYPES,
)
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from utils.models import DefaultAuthenticatedModel


class RhCommentModel(AbstractGenericReactionModel, DefaultAuthenticatedModel):
    """--- MODEL FIELDS ---"""

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
        null=True,
        max_length=1024,
        upload_to="uploads/rh_comment/%Y/%m/%d/",
        help_text="""Src may be blank but never null upon saving.""",
    )
    comment_content_json = JSONField(blank=True, null=True)
    comment_content_type = CharField(
        choices=RH_COMMENT_CONTENT_TYPES,
        default=QUILL_EDITOR,
        max_length=144,
    )
    is_removed = BooleanField(default=False)
    is_public = BooleanField(default=False)
    parent = ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=SET_NULL,
        related_name="children",
    )
    thread = ForeignKey(
        RhCommentThreadModel,
        db_index=True,
        on_delete=CASCADE,
        related_name="rh_comments",
    )

    # legacy_migration
    legacy_id = PositiveIntegerField(null=True, blank=True)
    legacy_model_type = CharField(
        choices=RH_COMMENT_MIGRATION_LEGACY_TYPES,
        default=LEGACY_COMMENT,
        max_length=144,
        blank=True,
        null=True,
    )

    """ --- PROPERTIES --- """

    @property
    def is_edited(self):
        return (self.updated_date - self.created_date).total_seconds() > 5

    @property
    def is_root_comment(self):
        return self.parent is None

    """ --- METHODS --- """

    @classmethod
    def create_from_data(cls, data):
        from researchhub_comment.serializers import RhCommentSerializer

        with transaction.atomic():
            thread_id = data.get("thread")
            user_id = data.get("created_by")
            comment_content_src_file = cls.get_comment_src_file_from_data(data)

            rh_comment_serializer = RhCommentSerializer(data=data)
            rh_comment_serializer.is_valid(raise_exception=True)
            rh_comment = rh_comment_serializer.save()
            rh_comment.comment_content_src.save(
                f"RH-THREAD-{thread_id}-COMMENT-{rh_comment.id}-user-{user_id}.txt",
                comment_content_src_file,
            )
            return rh_comment, rh_comment_serializer.data

    @staticmethod
    def get_comment_src_file_from_data(data):
        comment_content = data.get("comment_content_json")
        comment_content_src_file = ContentFile(
            json.dumps(comment_content).encode("utf8")
        )
        return comment_content_src_file
