from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from feed.hot_score import calculate_hot_score_for_item
from hub.models import Hub
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from user.related_models.author_model import Author
from utils.models import DefaultModel


class HotScoreV2Breakdown(models.Model):
    """Separate table for hot score v2 breakdown JSONB data to improve performance."""

    feed_entry = models.OneToOneField(
        "FeedEntry",
        on_delete=models.CASCADE,
        related_name="hot_score_breakdown_v2",
        db_index=True,
        help_text="The feed entry this breakdown belongs to.",
    )
    breakdown_data = models.JSONField(
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

    class Meta:
        db_table = "feed_hotscorev2breakdown"
        constraints = [
            models.UniqueConstraint(
                fields=["feed_entry"],
                name="unique_feed_entry_breakdown",
            ),
        ]

    def __str__(self):
        return f"HotScoreV2Breakdown for FeedEntry {self.feed_entry_id}"


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

    metrics = models.JSONField(
        encoder=DjangoJSONEncoder,
        default=dict,
        db_comment="A serialized JSON representation of the metrics for the item.",
        blank=False,
        null=False,
    )

    hubs = models.ManyToManyField(
        Hub,
        blank=True,
        related_name="feed_entries",
    )

    authors = models.ManyToManyField(
        Author,
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

    pdf_copyright_allows_display = models.BooleanField(
        default=False,
        help_text="Whether the PDF copyright allows display on our site.",
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
            models.Index(
                fields=["pdf_copyright_allows_display"],
                name="feed_pdf_no_display_idx",
                condition=models.Q(pdf_copyright_allows_display=False),
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

    def calculate_hot_score_v2(self):
        """Calculate hot score using new v2 algorithm and store breakdown."""
        from django.contrib.contenttypes.models import ContentType
        from django.core.exceptions import ObjectDoesNotExist

        from feed.hot_score import calculate_hot_score
        from feed.hot_score_breakdown import format_breakdown_from_calc_data

        try:
            # Get content type
            item = self.item
            if not item:
                try:
                    if self.hot_score_breakdown_v2:
                        self.hot_score_breakdown_v2.delete()
                except ObjectDoesNotExist:
                    pass
                return 0

            item_content_type = ContentType.objects.get_for_model(item)

            # Calculate score with components (single source of truth)
            calc_data = calculate_hot_score(
                self, item_content_type, return_components=True
            )

            if not calc_data:
                try:
                    if self.hot_score_breakdown_v2:
                        self.hot_score_breakdown_v2.delete()
                except ObjectDoesNotExist:
                    pass
                return 0

            # Format breakdown from calculation data
            breakdown_data = format_breakdown_from_calc_data(calc_data)

            _breakdown, _created = HotScoreV2Breakdown.objects.update_or_create(
                feed_entry=self,
                defaults={"breakdown_data": breakdown_data},
            )

            # Return the score
            return calc_data["final_score"]

        except Exception as e:
            import logging

            logging.getLogger(__name__).error(
                f"Error calculating hot score v2 for entry {self.id}: {e}"
            )
            try:
                if self.hot_score_breakdown_v2:
                    self.hot_score_breakdown_v2.delete()
            except ObjectDoesNotExist:
                pass
            # Fallback: calculate score directly
            score = calculate_hot_score_for_item(self)
            return score
