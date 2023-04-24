from django.contrib.contenttypes.fields import GenericRelation
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
from purchase.models import Purchase
from researchhub_comment.constants.rh_comment_content_types import (
    QUILL_EDITOR,
    RH_COMMENT_CONTENT_TYPES,
)
from researchhub_comment.constants.rh_comment_migration_legacy_types import (
    RH_COMMENT_MIGRATION_LEGACY_TYPES,
)
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_comment.tasks import celery_create_comment_content_src
from utils.models import DefaultAuthenticatedModel, SoftDeletableModel


class RhCommentModel(
    AbstractGenericReactionModel, SoftDeletableModel, DefaultAuthenticatedModel
):
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
    is_accepted_answer = BooleanField(null=True)
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
    purchases = GenericRelation(
        Purchase,
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="rh_comments",
    )
    bounties = GenericRelation(
        "reputation.Bounty",
        content_type_field="item_content_type",
        object_id_field="item_object_id",
    )
    bounty_solution = GenericRelation(
        "reputation.BountySolution",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="rh_comment",
    )
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="rh_comment",
    )

    # legacy_migration
    legacy_id = PositiveIntegerField(null=True, blank=True)
    legacy_model_type = CharField(
        choices=RH_COMMENT_MIGRATION_LEGACY_TYPES,
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

    @property
    def unified_document(self):
        return self.thread.unified_document

    @property
    def plain_text(self):
        plain_text = ""
        comment_json = self.comment_content_json
        ops = comment_json.get("ops", [])
        for op in ops:
            text = op.get("insert")
            # Ensuring it is a string
            plain_text += f"{text}"
        return plain_text

    @property
    def users_to_notify(self):
        if self.parent:
            return [self.parent.created_by]
        else:
            return [self.thread.content_object.created_by]

    """ --- METHODS --- """

    def update_comment_content(self):
        celery_create_comment_content_src.apply_async(
            (self.id, self.comment_content_json), countdown=2
        )

    def _update_related_discussion_count(self, amount):
        related_document = self.unified_document.get_document()
        if hasattr(related_document, "discussion_count"):
            related_document.discussion_count += amount
            related_document.save()

    def increment_discussion_count(self):
        self._update_related_discussion_count(1)

    def decrement_discussion_count(self):
        self._update_related_discussion_count(-1)

    @classmethod
    def create_from_data(cls, data):
        from researchhub_comment.serializers import RhCommentSerializer

        rh_comment_serializer = RhCommentSerializer(data=data)
        rh_comment_serializer.is_valid(raise_exception=True)
        rh_comment = rh_comment_serializer.save()
        celery_create_comment_content_src.apply_async(
            (rh_comment.id, data.get("comment_content_json")), countdown=2
        )
        rh_comment.increment_discussion_count()
        return rh_comment, rh_comment_serializer.data
