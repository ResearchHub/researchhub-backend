from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.functions import TruncDate

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
        null=True,
        blank=True,
    )
    external_user_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text=(
            "External user ID (from Amplitude analytics_id) for anonymous and "
            "authenticated users"
        ),
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
    impression = models.TextField(
        null=True,
        blank=True,
        help_text="Pipe-delimited unified document IDs from Amplitude events",
    )

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["external_user_id"]),
            models.Index(fields=["event"]),
            models.Index(fields=["event_timestamp"]),
            models.Index(
                fields=["is_synced_with_personalize"], name="idx_synced_personalize"
            ),
        ]
        constraints = [
            # Strict uniqueness for one-time actions
            models.UniqueConstraint(
                fields=[
                    "user",
                    "event",
                    "unified_document",
                    "content_type",
                    "object_id",
                ],
                condition=models.Q(
                    event__in=[
                        "UPVOTE",
                        "COMMENT_CREATED",
                        "PEER_REVIEW_CREATED",
                        "DOCUMENT_SAVED_TO_LIST",
                    ],
                    user__isnull=False,
                ),
                name="unique_non_repeatable_interactions",
            ),
            # Daily uniqueness for repeatable events
            models.UniqueConstraint(
                TruncDate("event_timestamp"),
                "external_user_id",
                "event",
                "unified_document",
                "content_type",
                "object_id",
                condition=models.Q(
                    event__in=[
                        "FEED_ITEM_CLICK",
                        "PAGE_VIEW",
                        "DOCUMENT_TAB_CLICKED",
                        "FEED_ITEM_ABSTRACT_EXPANDED",
                    ]
                ),
                name="unique_daily_repeatable_interactions",
            ),
        ]

    def __str__(self):
        user_identifier = (
            self.user_id
            if self.user_id
            else f"external_user_id:{self.external_user_id}"
        )
        return (
            f"UserInteraction: {user_identifier} - {self.event} - "
            f"{self.unified_document_id}"
        )
