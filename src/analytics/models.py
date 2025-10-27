from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from analytics.constants import EVENT_CHOICES
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from utils.models import DefaultModel


class WebsiteVisits(models.Model):
    uuid = models.CharField(max_length=36)
    saw_signup_banner = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.uuid}"


class UserInteractions(DefaultModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="user_interactions",
    )
    event = models.CharField(
        max_length=50,
        choices=EVENT_CHOICES,
    )
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
    )
    object_id = models.PositiveIntegerField()
    item = GenericForeignKey("content_type", "object_id")
    event_timestamp = models.DateTimeField()
    is_synced_with_personalize = models.BooleanField(default=False)
    personalize_rec_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["event"]),
            models.Index(fields=["event_timestamp"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "event",
                    "unified_document",
                    "content_type",
                    "object_id",
                ],
                name="unique_user_event_interaction",
            )
        ]

    def __str__(self):
        return (
            f"UserInteraction: {self.user_id} - {self.event} - "
            f"{self.unified_document_id}"
        )
