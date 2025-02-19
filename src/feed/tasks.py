from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
import logging
from feed.models import FeedEntry
from researchhub.celery import app
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
    parent_item = parent_content_type.get_object_for_this_type(id=parent_item_id)
    if user_id:
        user = User.objects.get(id=user_id)
    else:
        user = None

    action_date = item.created_date
    if action == FeedEntry.PUBLISH and item_content_type.model == "paper":
        action_date = item.paper_publish_date

    # Create and return the feed entry
    try:
        return FeedEntry.objects.create(
        user=user,
        item=item,
        content_type=item_content_type,
        object_id=item_id,
        action=action,
        action_date=action_date,
        parent_item=parent_item,
        parent_content_type=parent_content_type,
            parent_object_id=parent_item_id,
        )
    except IntegrityError:
        # Ignore error if feed entry already exists
        logger.warning(f"Feed entry already exists for item_id={item_id} content_type={item_content_type.model} parent_item_id={parent_item_id} parent_content_type={parent_content_type.model}")


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
