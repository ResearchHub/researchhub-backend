import logging
import time
from typing import Any, Optional

from django.contrib.contenttypes.models import ContentType

import utils.locking as lock
from feed.models import FeedEntry
from feed.serializers import serialize_feed_item, serialize_feed_metrics
from researchhub.celery import app
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from utils import sentry

logger = logging.getLogger(__name__)


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

    # Create and return the feed entry
    try:
        feed_entry, created = FeedEntry.objects.update_or_create(
            user=user,
            content_type=item_content_type,
            object_id=item_id,
            action=action,
            defaults={
                "content": content,
                "action_date": action_date,
                "metrics": metrics,
                "unified_document": unified_document,
            },
        )
        if hub_ids:
            feed_entry.hubs.add(*hub_ids)
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

    feed_entry.content = content
    feed_entry.metrics = metrics
    feed_entry.hot_score = feed_entry.calculate_hot_score()
    feed_entry.save(update_fields=["content", "metrics", "hot_score"])


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

        feed_entry.content = content
        feed_entry.metrics = metrics
        feed_entry.hot_score = feed_entry.calculate_hot_score()
        feed_entry.save(update_fields=["content", "metrics", "hot_score"])


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
        _refresh_feed_hot_scores()
    finally:
        lock.release(key)
        logger.info(f"Released lock {key}")


def _refresh_feed_hot_scores():
    """
    Refresh both v1 (deprecated) and v2 (new) hot scores.
    This allows A/B testing between the two algorithms.
    """
    start_time = time.time()
    count = 0
    batch_size = 1000
    total_entries = FeedEntry.objects.count()

    # Process in batches
    for offset in range(0, total_entries, batch_size):
        entries_to_update = []

        # Process a batch of entries
        batch = list(
            FeedEntry.objects.prefetch_related("item")[offset : (offset + batch_size)]
        )

        # Calculate both hot scores for each entry in the batch
        for feed_entry in batch:
            if feed_entry.item:
                # Calculate both v1 and v2 scores
                feed_entry.hot_score = feed_entry.calculate_hot_score()
                feed_entry.hot_score_v2 = feed_entry.calculate_hot_score_v2()
                entries_to_update.append(feed_entry)

        # Bulk update entries with both hot scores
        if entries_to_update:
            from django.db import connection

            with connection.cursor() as cursor:
                batch_params = [
                    (entry.hot_score, entry.hot_score_v2, entry.id)
                    for entry in entries_to_update
                ]
                cursor.executemany(
                    "UPDATE feed_feedentry SET hot_score = %s, "
                    "hot_score_v2 = %s WHERE id = %s",
                    batch_params,
                )

        count += len(batch)
        logger.info(f"Processed {count} of {total_entries} feed entries")

    duration = time.time() - start_time
    logger.info(f"Refreshed both v1 and v2 hot scores in {duration:.2f}s")
    sentry.log_info(f"Refreshed both v1 and v2 hot scores in {duration:.2f}s")


@app.task
def refresh_popular_feed_entries():
    import time

    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    start = time.time()
    logger.info("Refreshing popular feed entries...")

    factory = APIRequestFactory()
    django_request = factory.get(
        "/api/feed/",
        {
            "feed_view": "popular",
        },
        HTTP_HOST="localhost",
    )

    drf_request = Request(django_request)

    viewset = FeedViewSet()
    viewset.setup(drf_request, None)
    viewset.format_kwarg = None

    # Call the list() method
    viewset.list(drf_request)

    duration = time.time() - start
    logger.info(f"Popular feed entries refreshed ({duration:.2f}s)")
