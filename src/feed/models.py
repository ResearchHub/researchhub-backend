from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from feed.hot_score import calculate_hot_score_for_item
from feed.hot_score_DEPRECATED import calculate_hot_score_for_item_DEPRECATED
from hub.models import Hub
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

    hot_score = models.IntegerField(
        default=0,
        help_text="Feed ranking score (v1 - DEPRECATED).",
    )

    hot_score_v2 = models.IntegerField(
        default=0,
        help_text="New hot score algorithm (v2)",
        db_index=True,
    )

    hot_score_v2_breakdown = models.JSONField(
        encoder=DjangoJSONEncoder,
        default=dict,
        blank=True,
        null=False,
        db_comment="Detailed breakdown of hot_score_v2 calculation.",
        help_text=(
            "Contains equation, steps, signals, time_factors, and calculation "
            "details for transparency and debugging."
        ),
    )

    metrics = models.JSONField(
        encoder=DjangoJSONEncoder,
        default=dict,
        db_comment="A serialized JSON representation of the metrics for the item.",
        blank=False,
        null=False,
    )

    # The hubs associated with the feed entry.
    hubs = models.ManyToManyField(
        Hub,
        blank=True,
        related_name="feed_entries",
    )

    action = models.TextField(choices=action_choices)
    action_date = models.DateTimeField(db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        related_name="feed_entries",
        db_comment=(
            "The unified document associated with the feed entry. "
            "Directly added to the feed entry for performance reasons."
        ),
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["content_type", "object_id", "-action_date"],
                name="feed_partition_action_idx",
            ),
            models.Index(
                fields=["-action_date"],
                name="feed_action_date_idx",
            ),
            models.Index(
                fields=["created_date"],
                name="feed_created_date_idx",
            ),
            models.Index(
                fields=["-hot_score"],
                name="feed_hot_score_idx",
            ),
        ]
        constraints = [
            # Constraint for entries WITH a user
            models.UniqueConstraint(
                fields=[
                    "content_type",
                    "object_id",
                    "action",
                    "user",
                ],
                name="unique_feed_entry_with_user",
                condition=models.Q(user__isnull=False),
            ),
            # Constraint for entries WITHOUT a user (system entries)
            models.UniqueConstraint(
                fields=[
                    "content_type",
                    "object_id",
                    "action",
                ],
                name="unique_feed_entry_without_user",
                condition=models.Q(user__isnull=True),
            ),
        ]

    def calculate_hot_score(self):
        """Calculate hot score using DEPRECATED algorithm."""
        return calculate_hot_score_for_item_DEPRECATED(self)

    def calculate_hot_score_v2(self):
        """Calculate hot score using new v2 algorithm and store breakdown."""
        from django.contrib.contenttypes.models import ContentType

        from feed.hot_score import calculate_hot_score
        from feed.hot_score_breakdown import format_breakdown_from_calc_data

        try:
            # Get content type
            item = self.item
            if not item:
                self.hot_score_v2_breakdown = {}
                return 0

            item_content_type = ContentType.objects.get_for_model(item)

            # Calculate score with components (single source of truth)
            calc_data = calculate_hot_score(
                self, item_content_type, return_components=True
            )

            if not calc_data:
                self.hot_score_v2_breakdown = {}
                return 0

            # Format breakdown from calculation data
            self.hot_score_v2_breakdown = format_breakdown_from_calc_data(calc_data)

            # Return the score
            return calc_data["final_score"]

        except Exception as e:
            import logging

            logging.getLogger(__name__).error(
                f"Error calculating hot score v2 for entry {self.id}: {e}"
            )
            self.hot_score_v2_breakdown = {}
            # Fallback: calculate score directly
            score = calculate_hot_score_for_item(self)
            return score
