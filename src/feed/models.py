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

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")

    parent_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    parent_object_id = models.PositiveIntegerField(null=True, blank=True)
    parent_item = GenericForeignKey("parent_content_type", "parent_object_id")

    action = models.TextField(choices=action_choices)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
