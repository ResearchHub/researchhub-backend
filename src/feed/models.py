from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from researchhub.celery import app
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
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["parent_content_type", "parent_object_id"],
                name="feed_parent_lookup_idx",
            )
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


@app.task
def create_feed_entry(
    item_id,
    item_content_type_id,
    action,
    parent_item_id,
    parent_content_type_id,
    user_id=None,
):
    # Get the ContentType objects
    item_content_type = ContentType.objects.get(id=item_content_type_id)
    parent_content_type = ContentType.objects.get(id=parent_content_type_id)

    # Get the actual model instances
    item = item_content_type.get_object_for_this_type(id=item_id)
    parent_item = parent_content_type.get_object_for_this_type(id=parent_item_id)
    if user_id:
        user = User.objects.get(id=user_id)
    else:
        user = None
    # Create the feed entry
    FeedEntry.objects.create(
        user=user,
        item=item,
        content_type=item_content_type,
        object_id=item_id,
        action=action,
        parent_item=parent_item,
        parent_content_type=parent_content_type,
        parent_object_id=parent_item_id,
    )


@app.task
def delete_feed_entry(
    item_id,
    item_content_type_id,
    parent_item_id,
    parent_item_content_type_id,
):
    item_content_type = ContentType.objects.get(id=item_content_type_id)
    parent_item_content_type = ContentType.objects.get(id=parent_item_content_type_id)
    feed_entry = FeedEntry.objects.get(
        object_id=item_id,
        content_type=item_content_type,
        parent_object_id=parent_item_id,
        parent_content_type=parent_item_content_type,
    )
    feed_entry.delete()
