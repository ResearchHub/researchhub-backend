import logging
import time
from typing import Any, Optional

from django.contrib.contenttypes.models import ContentType

from feed.models import FeedEntry, FeedEntryLatest, FeedEntryPopular
from feed.serializers import serialize_feed_item, serialize_feed_metrics
from researchhub.celery import app
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User

logger = logging.getLogger(__name__)


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
        feed_entry, _ = FeedEntry.objects.update_or_create(
            user=user,
            content=content,
            content_type=item_content_type,
            object_id=item_id,
            action=action,
            action_date=action_date,
            metrics=metrics,
            parent_content_type=parent_content_type,
            parent_object_id=parent_item_id,
            unified_document=unified_document,
        )
        return feed_entry
    except Exception as e:
        # Ignore error if feed entry already exists
        logger.warning(
            f"Failed to save feed entry for item_id={item_id} content_type={item_content_type.model} parent_item_id={parent_item_id} parent_content_type={parent_content_type.model}: {e}"
        )


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
        feed_entry.save(update_fields=["content", "metrics"])


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
    parent_item_id,
    parent_item_content_type_id,
):
    item_content_type = ContentType.objects.get(id=item_content_type_id)
    parent_item_content_type = ContentType.objects.get(id=parent_item_content_type_id)
    FeedEntry.objects.filter(
        object_id=item_id,
        content_type=item_content_type,
        parent_object_id=parent_item_id,
        parent_content_type=parent_item_content_type,
    ).delete()


@app.task
def refresh_feed():
    """
    Refreshes the materialized feed entries that are managed in a materialized
    view in the database.
    """
    start_time = time.time()
    FeedEntryLatest.refresh()
    FeedEntryPopular.refresh()
    duration = time.time() - start_time
    logger.info(f"Refreshed materialized feed entries in {duration:.2f}s")
