import logging
import time
from datetime import timedelta
from typing import Any, Optional

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

import utils.locking as lock
from feed.models import FeedEntry
from feed.serializers import serialize_feed_item, serialize_feed_metrics
from paper.related_models.paper_model import Paper
from researchhub.celery import app
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from user.related_models.author_model import Author
from utils import sentry

logger = logging.getLogger(__name__)


# Default content types for hot score refresh
def _get_default_content_types():
    return [
        ContentType.objects.get_for_model(Paper),
        ContentType.objects.get_for_model(ResearchhubPost),
    ]


@app.task
def create_feed_entry(
    item_id,
    item_content_type_id,
    action,
    hub_ids=None,
    user_id=None,
):
    # Get the ContentType objects
    item_content_type = ContentType.objects.get(id=item_content_type_id)

    # Get the actual model instances
    item = item_content_type.get_object_for_this_type(id=item_id)
    if user_id:
        user = User.objects.get(id=user_id)
    else:
        user = None

    unified_document = _get_unified_document(item, item_content_type)

    content = serialize_feed_item(item, item_content_type)

    metrics = serialize_feed_metrics(item, item_content_type)

    action_date = item.created_date
    if action == FeedEntry.PUBLISH and item_content_type.model == "paper":
        action_date = item.paper_publish_date

    # Get authors for the item
    authors = _get_authors_for_item(item, item_content_type)

    # Create and return the feed entry
    try:
        feed_entry, _ = FeedEntry.objects.update_or_create(
            content_type=item_content_type,
            object_id=item_id,
            action=action,
            defaults={
                "action_date": action_date,
                "content": content,
                "metrics": metrics,
                "unified_document": unified_document,
                "user": user,
            },
        )
        if hub_ids:
            feed_entry.hubs.add(*hub_ids)
        if authors:
            feed_entry.authors.set(authors)
        return feed_entry
    except Exception as e:
        # Ignore error if feed entry already exists
        logger.warning(
            f"Failed to save feed entry for item_id={item_id} "
            f"content_type={item_content_type.model}: {e}"
        )


@app.task
def refresh_feed_entry(feed_entry_id):
    feed_entry = FeedEntry.objects.get(id=feed_entry_id)
    content = serialize_feed_item(feed_entry.item, feed_entry.content_type)
    metrics = serialize_feed_metrics(feed_entry.item, feed_entry.content_type)

    # Get authors for the item
    authors = _get_authors_for_item(feed_entry.item, feed_entry.content_type)

    feed_entry.content = content
    feed_entry.metrics = metrics
    feed_entry.hot_score = feed_entry.calculate_hot_score()
    feed_entry.save(update_fields=["content", "metrics", "hot_score"])

    # Update authors separately (ManyToMany field)
    if authors:
        feed_entry.authors.set(authors)


@app.task
def refresh_feed_entries_for_objects(item_id, item_content_type_id):
    item_content_type = ContentType.objects.get(id=item_content_type_id)

    feed_entries = FeedEntry.objects.filter(
        object_id=item_id,
        content_type=item_content_type,
    )

    for feed_entry in feed_entries:
        content = serialize_feed_item(feed_entry.item, item_content_type)

        metrics = serialize_feed_metrics(feed_entry.item, item_content_type)

        # Get authors for the item
        authors = _get_authors_for_item(feed_entry.item, item_content_type)

        feed_entry.content = content
        feed_entry.metrics = metrics
        feed_entry.hot_score = feed_entry.calculate_hot_score()
        feed_entry.save(update_fields=["content", "metrics", "hot_score"])

        # Update authors separately (ManyToMany field)
        if authors:
            feed_entry.authors.set(authors)


@app.task
def update_feed_metrics(item_id, item_content_type_id, metrics):
    item_content_type = ContentType.objects.get(id=item_content_type_id)

    FeedEntry.objects.filter(
        object_id=item_id,
        content_type=item_content_type,
    ).update(metrics=metrics)


def _get_unified_document(
    item: Any, item_content_type: ContentType
) -> Optional[ResearchhubUnifiedDocument]:
    """
    Extract unified document from different content types.

    Returns:
        ResearchhubUnifiedDocument or None if item type isnot supported.
    """
    match item_content_type.model:
        case "bounty" | "paper" | "researchhubpost":
            doc = item.unified_document
        case "rhcommentmodel":
            doc = item.thread.unified_document
        case _:
            doc = None

    return doc


def _get_authors_for_item(item: Any, item_content_type: ContentType) -> list[Author]:
    """
    Extract authors from different content types.

    Returns:
        List of Author objects associated with the item.
    """
    authors = []

    match item_content_type.model:
        case "paper" | "researchhubpost":
            # Papers and Posts have a ManyToMany relationship with authors
            if hasattr(item, "authors"):
                authors = list(item.authors.all())
        case "rhcommentmodel":
            # Comments have a created_by user with an author_profile
            if (
                hasattr(item, "created_by")
                and item.created_by
                and hasattr(item.created_by, "author_profile")
                and item.created_by.author_profile
            ):
                authors = [item.created_by.author_profile]

    return authors


@app.task
def delete_feed_entry(
    item_id,
    item_content_type_id,
    hub_ids=None,
):
    item_content_type = ContentType.objects.get(id=item_content_type_id)

    feed_entries = FeedEntry.objects.filter(
        object_id=item_id,
        content_type=item_content_type,
    )

    if hub_ids:
        # drop hub relations
        for entry in feed_entries:
            entry.hubs.remove(*hub_ids)
            # if no hubs remain, delete the entry entirely
            if not entry.hubs.exists():
                entry.delete()
    else:
        feed_entries.delete()


@app.task
def refresh_feed_hot_scores():
    key = lock.name("refresh_feed_hot_scores")
    if not lock.acquire(key):
        logger.warning(f"Already locked {key}, skipping task")
        return False

    try:
        # Uses default 30-day lookback for papers and posts only
        stats = refresh_feed_hot_scores_batch(
            queryset=None,
            update_v1=True,
            update_v2=True,
            content_types=None,
        )
        logger.info(f"Refreshed hot scores: {stats}")
        sentry.log_info(f"Refreshed hot scores: {stats}")
        return stats
    finally:
        lock.release(key)
        logger.info(f"Released lock {key}")


def refresh_feed_hot_scores_batch(
    queryset=None,
    batch_size=1000,
    update_v1=True,
    update_v2=True,
    days_back=30,
    content_types=None,
    progress_callback=None,
):
    """
    Refresh hot scores for feed entries with optional filtering.
    """
    start_time = time.time()

    # Build default queryset if none provided
    if queryset is None:
        queryset = FeedEntry.objects.all()

        # Apply date filter
        if days_back is not None:
            cutoff_date = timezone.now() - timedelta(days=days_back)
            queryset = queryset.filter(created_date__gte=cutoff_date)

        # Apply content type filter with defaults
        if content_types is None:
            content_types = _get_default_content_types()

        if content_types:
            queryset = queryset.filter(content_type__in=content_types)

    # Apply proper prefetching
    queryset = queryset.select_related(
        "content_type", "unified_document"
    ).prefetch_related("item")

    total_entries = queryset.count()
    processed = 0
    updated = 0
    errors = 0

    # Determine which fields to update
    update_fields = []
    if update_v1:
        update_fields.append("hot_score")
    if update_v2:
        update_fields.append("hot_score_v2")

    if not update_fields:
        logger.warning("No update fields specified, skipping hot score refresh")
        return {
            "processed": 0,
            "updated": 0,
            "errors": 0,
            "duration": 0,
        }

    # Process in batches
    for offset in range(0, total_entries, batch_size):
        entries_to_update = []

        # Process a batch of entries
        batch = list(queryset[offset : (offset + batch_size)])

        # Calculate hot scores for each entry in the batch
        for feed_entry in batch:
            try:
                if not feed_entry.item:
                    processed += 1
                    continue

                # Calculate scores based on flags
                if update_v1:
                    feed_entry.hot_score = feed_entry.calculate_hot_score()
                if update_v2:
                    feed_entry.hot_score_v2 = feed_entry.calculate_hot_score_v2()

                entries_to_update.append(feed_entry)

            except Exception as e:
                errors += 1
                logger.error(f"Error calculating score for entry {feed_entry.id}: {e}")
                continue

        # Bulk update entries using Django ORM
        if entries_to_update:
            try:
                FeedEntry.objects.bulk_update(
                    entries_to_update, update_fields, batch_size=batch_size
                )
                updated += len(entries_to_update)
            except Exception as e:
                errors += len(entries_to_update)
                logger.error(f"Error bulk updating batch: {e}")

        processed += len(batch)

        # Call progress callback if provided
        if progress_callback:
            progress_callback(processed, total_entries, updated, errors)
        else:
            logger.info(f"Processed {processed} of {total_entries} feed entries")

    duration = time.time() - start_time
    logger.info(
        f"Refreshed hot scores in {duration:.2f}s: "
        f"processed={processed}, updated={updated}, errors={errors}"
    )

    return {
        "processed": processed,
        "updated": updated,
        "errors": errors,
        "duration": duration,
    }
