from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from user.models import User
from utils.models import DefaultModel


class FeedEntry(DefaultModel):
    PUBLISH = "PUBLISH"
    action_choices = [
        (PUBLISH, "PUBLISH"),
    ]

    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="feed_entries"
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")

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
