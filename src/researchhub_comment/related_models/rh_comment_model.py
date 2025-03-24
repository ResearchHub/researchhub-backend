from django.contrib.contenttypes.fields import GenericRelation
from django.db.models import (
    CASCADE,
    SET_NULL,
    BooleanField,
    CharField,
    FileField,
    ForeignKey,
    JSONField,
    TextField,
)

from discussion.reaction_models import AbstractGenericReactionModel
from purchase.models import Purchase
from researchhub_comment.constants.rh_comment_content_types import (
    QUILL_EDITOR,
    RH_COMMENT_CONTENT_TYPES,
)
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    RH_COMMENT_THREAD_TYPES,
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
        related_query_name="rh_comment",
    )
    bounty_solution = GenericRelation(
        "reputation.BountySolution",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="rh_comment",
    )
    comment_type = CharField(
        max_length=144,
        choices=RH_COMMENT_THREAD_TYPES,
        default=GENERIC_COMMENT,
    )
    actions = GenericRelation(
        "user.Action",
        object_id_field="object_id",
        content_type_field="content_type",
        related_query_name="rh_comment",
    )
    reviews = GenericRelation("review.Review")

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
    def is_public_comment(self):
        from citation.models import CitationEntry

        return not isinstance(self.thread.content_object, CitationEntry)

    @property
    def plain_text(self):
        plain_text = ""
        comment_json = self.comment_content_json
        ops = comment_json.get("ops", [])
        for op in ops:
            text = op.get("insert")
            # Ensuring it is a string
            plain_text = f"{plain_text}{text}"
        return plain_text

    @property
    def users_to_notify(self):
        if self.parent:
            users_to_notify = self.parent.created_by
        else:
            users_to_notify = self.thread.content_object.created_by

        if users_to_notify:
            return [users_to_notify]
        return []

    @property
    def children_count(self):
        return self.children.count()

    """ --- METHODS --- """

    # Recursively counts all direct and indirect children of a comment.
    def get_total_children_count(self):
        total_count = 0
        children = self.children.all()  # Get direct children of the comment

        for child in children:
            # Count each child and recursively count their children
            total_count += 1 + child.get_total_children_count()

        return total_count

    def update_comment_content(self):
        celery_create_comment_content_src.apply_async(
            (self.id, self.comment_content_json), countdown=2
        )

    def _update_related_discussion_count(self, amount):
        from citation.models import CitationEntry

        thread = self.thread
        if isinstance(self.thread.content_object, CitationEntry):
            return

        related_document = thread.unified_document.get_document()
        if hasattr(related_document, "discussion_count"):
            related_document.discussion_count += amount
            related_document.save(update_fields=["discussion_count"])

    def refresh_related_discussion_count(self):
        from citation.models import CitationEntry

        thread = self.thread
        if isinstance(self.thread.content_object, CitationEntry):
            return

        related_document = thread.unified_document.get_document()

        if hasattr(related_document, "discussion_count"):
            related_document.discussion_count = related_document.get_discussion_count()

            related_document.save(update_fields=["discussion_count"])

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
