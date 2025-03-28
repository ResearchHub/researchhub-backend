from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from utils.models import DefaultModel


class FeedEntry(DefaultModel):
    OPEN = "OPEN"
    PUBLISH = "PUBLISH"
    action_choices = [
        (OPEN, "OPEN"),
        (PUBLISH, "PUBLISH"),
    ]

    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="feed_entries"
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")

    content = models.JSONField(
        encoder=DjangoJSONEncoder,
        default=dict,
        db_comment="A serialized JSON representation of the item.",
        blank=False,
        null=False,
    )

    metrics = models.JSONField(
        encoder=DjangoJSONEncoder,
        default=dict,
        db_comment="A serialized JSON representation of the metrics for the item.",
        blank=False,
        null=False,
    )

    parent_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="parent_feed_entries",
        null=True,
        blank=True,
    )
    parent_object_id = models.PositiveIntegerField(null=True, blank=True)
    parent_item = GenericForeignKey("parent_content_type", "parent_object_id")

    action = models.TextField(choices=action_choices)
    action_date = models.DateTimeField(db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        related_name="feed_entries",
        db_comment="The unified document associated with the feed entry. Directly added to the feed entry for performance reasons.",
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["parent_content_type", "parent_object_id"],
                name="feed_parent_lookup_idx",
            ),
            models.Index(
                fields=["content_type", "object_id", "-action_date"],
                name="feed_partition_action_idx",
            ),
            models.Index(
                fields=["-action_date"],
                name="feed_action_date_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "content_type",
                    "object_id",
                    "parent_content_type",
                    "parent_object_id",
                    "action",
                    "user",
                ],
                name="unique_feed_entry",
            )
        ]
