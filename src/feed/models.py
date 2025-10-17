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
        """Calculate hot score using new v2 algorithm."""
        return calculate_hot_score_for_item(self)


class FeedEntryPopular(models.Model):
    """
    Materialized view for popular feed entries, based on the `FeedEntry` model.
    This view is used to optimize the performance of feed entry queries.
    """

    id = models.BigIntegerField(primary_key=True)

    action = models.TextField(choices=FeedEntry.action_choices)
    action_date = models.DateTimeField()
    content = models.JSONField(default=dict)

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.DO_NOTHING,
        db_column="content_type_id",
        related_name="popular_feed_entries",
    )
    hot_score = models.FloatField()
    # The hubs associated with the feed entry.
    hubs = models.ManyToManyField(
        Hub,
        through="FeedEntryPopularHubs",
        blank=True,
        related_name="popular_feed_entries",
    )
    item = GenericForeignKey("content_type", "object_id")
    object_id = models.PositiveIntegerField()
    metrics = models.JSONField(default=dict)
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.DO_NOTHING,
        db_column="unified_document_id",
        related_name="popular_feed_entries",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        related_name="popular_feed_entries",
        null=True,
        blank=True,
    )

    created_date = models.DateTimeField()
    updated_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "feed_feedentry_popular"
        ordering = ["-hot_score"]

    @classmethod
    def refresh(cls):
        """
        Refresh the materialized view.
        """
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY feed_feedentry_popular"
            )
            cursor.execute("SELECT pg_prewarm('feed_feedentry_popular')")


class FeedEntryPopularHubs(models.Model):
    feedentrypopular = models.ForeignKey(
        "FeedEntryPopular",
        db_column="feedentry_id",
        on_delete=models.DO_NOTHING,
    )
    hub = models.ForeignKey(
        Hub,
        db_column="hub_id",
        on_delete=models.DO_NOTHING,
    )

    class Meta:
        managed = False
        db_table = "feed_feedentry_hubs"
        unique_together = (("feedentrypopular", "hub"),)


class FeedEntryLatest(models.Model):
    """
    Materialized view for latest feed entries, based on the `FeedEntry` model.
    This view is used to optimize the performance of feed entry queries.
    """

    id = models.BigIntegerField(primary_key=True)

    action = models.TextField(choices=FeedEntry.action_choices)
    action_date = models.DateTimeField()
    content = models.JSONField(default=dict)

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.DO_NOTHING,
        db_column="content_type_id",
        related_name="latest_feed_entries",
    )
    # The hubs associated with the feed entry.
    hubs = models.ManyToManyField(
        Hub,
        through="FeedEntryLatestHubs",
        related_name="latest_feed_entries",
        blank=True,
    )
    item = GenericForeignKey("content_type", "object_id")
    object_id = models.PositiveIntegerField()
    metrics = models.JSONField(default=dict)
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.DO_NOTHING,
        db_column="unified_document_id",
        related_name="latest_feed_entries",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        db_column="user_id",
        related_name="latest_feed_entries",
        null=True,
        blank=True,
    )

    created_date = models.DateTimeField()
    updated_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "feed_feedentry_latest"
        ordering = ["-action_date"]

    @classmethod
    def refresh(cls):
        """
        Refresh the materialized view.
        """
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY feed_feedentry_latest"
            )
            cursor.execute("SELECT pg_prewarm('feed_feedentry_latest')")


class FeedEntryLatestHubs(models.Model):
    feedentrylatest = models.ForeignKey(
        "FeedEntryLatest",
        db_column="feedentry_id",
        on_delete=models.DO_NOTHING,
    )
    hub = models.ForeignKey(
        Hub,
        db_column="hub_id",
        on_delete=models.DO_NOTHING,
    )

    class Meta:
        managed = False
        db_table = "feed_feedentry_hubs"
        unique_together = (("feedentrylatest", "hub"),)
