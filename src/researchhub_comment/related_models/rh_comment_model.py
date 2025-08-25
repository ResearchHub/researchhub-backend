import json

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
    FloatField,
)

from discussion.models import AbstractGenericReactionModel
from purchase.models import Purchase
from researchhub_comment.constants.rh_comment_content_types import (
    QUILL_EDITOR,
    RH_COMMENT_CONTENT_TYPES,
    TIPTAP,
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
    ai_score = FloatField(
        null=True,
        blank=True,
        help_text="AI-generated probability in [0,1]. Use -1 to indicate scoring error.",
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
    def plain_text(self):
        """Return the raw text contained in the comment body.

        The implementation must support the two currently-used rich-text
        formats:

        1. **QUILL** – `comment_content_json` is expected to be a dict (or JSON
           encoded string) with an ``ops`` list.  Each item in that list may
           contain an ``insert`` key with the text.

        2. **TIPTAP** – `comment_content_json` is a JSON representation of the
           ProseMirror node tree.  We need to recursively walk the tree and
           concatenate the content of nodes whose ``type`` is ``"text"``.

        In addition, the method guards against malformed / unexpected data so
        that property access never raises.
        """

        if not self.comment_content_json:
            return ""

        # Accept either python dict or JSON encoded str
        try:
            comment_json = (
                json.loads(self.comment_content_json)
                if isinstance(self.comment_content_json, str)
                else self.comment_content_json
            )
        except (ValueError, TypeError):
            # Return empty string if json cannot be parsed
            return ""

        # Handle TIPTAP format first because it does not contain `ops`
        if self.comment_content_type == TIPTAP:

            def _extract_text(node):
                """Recursively extract text from a Tiptap/ProseMirror node."""
                if isinstance(node, dict):
                    # If this node is a text node
                    if node.get("type") == "text" and "text" in node:
                        return node.get("text", "")

                    # If the node has children, iterate through them
                    children = node.get("content")
                    if isinstance(children, list):
                        return "".join(_extract_text(child) for child in children)

                elif isinstance(node, list):
                    return "".join(_extract_text(child) for child in node)

                return ""

            return _extract_text(comment_json)

        # Default / QUILL behaviour
        ops = comment_json.get("ops", []) if isinstance(comment_json, dict) else []
        plain_text_parts = []
        for op in ops:
            text = op.get("insert", "") if isinstance(op, dict) else ""
            if isinstance(text, str):
                plain_text_parts.append(text)
        return "".join(plain_text_parts)

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
        """Return the total number of **direct and indirect** children, **including
        censored / soft-deleted comments**.

        The default related manager (`self.children`) only yields comments from
        the default manager (i.e. *non-removed* ones).  For discussion metrics
        we need to include comments that have been *censored* (soft-deleted)
        because they still participate in the thread and must be counted.  To
        achieve this we query through `RhCommentModel.all_objects`, which does
        **not** filter out removed comments.
        """

        from researchhub_comment.models import (
            RhCommentModel,  # local import to avoid circular
        )

        total_count = 0

        # Fetch **all** direct children regardless of `is_removed` status so we
        # can traverse into the sub-tree even if an intermediate node is
        # censored.  We will *only* count the child itself if it is **not**
        # removed.
        children_qs = RhCommentModel.all_objects.filter(parent=self)

        for child in children_qs:
            # Include the child in the tally only if it hasn't been censored
            if not child.is_removed:
                total_count += 1

            # Always recurse into the child's descendants – they might contain
            # visible comments even when the parent is censored.
            total_count += child.get_total_children_count()

        return total_count

    def update_comment_content(self):
        celery_create_comment_content_src.apply_async(
            (self.id, self.comment_content_json), countdown=2
        )

    def _update_related_discussion_count(self, amount):
        thread = self.thread
        related_document = thread.unified_document.get_document()
        if hasattr(related_document, "discussion_count"):
            related_document.discussion_count += amount
            related_document.save(update_fields=["discussion_count"])

    def refresh_related_discussion_count(self):
        thread = self.thread
        related_document = thread.unified_document.get_document()

        # Ensure the document has the `rh_threads` relation which provides the
        # custom manager with the `get_discussion_aggregates` helper.
        if hasattr(related_document, "rh_threads") and hasattr(
            related_document, "discussion_count"
        ):
            related_document.discussion_count = related_document.get_discussion_count()
            related_document.save(update_fields=["discussion_count"])

    @classmethod
    def create_from_data(cls, data):
        from researchhub_comment.serializers import RhCommentSerializer

        rh_comment_serializer = RhCommentSerializer(data=data)
        rh_comment_serializer.is_valid(raise_exception=True)
        rh_comment = rh_comment_serializer.save()
        celery_create_comment_content_src.apply_async(
            (rh_comment.id, data.get("comment_content_json")), countdown=2
        )
        rh_comment.refresh_related_discussion_count()
        return rh_comment, rh_comment_serializer.data
