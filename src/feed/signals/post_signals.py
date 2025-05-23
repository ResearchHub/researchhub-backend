import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from researchhub_document.models import ResearchhubPost

"""
Signal handlers for ResearchhubPost model.

The signal handlers are responsbile for creating and deleting feed entries
when posts are created and deleted, respectively.
"""

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ResearchhubPost, dispatch_uid="post_create_feed_entry")
def handle_post_create_feed_entry(sender, instance, **kwargs):
    """
    When a post is created, create feed entries for all hubs associated with the
    researchhub document that the post is associated with.
    """
    try:
        _create_post_feed_entries(instance)
    except Exception as e:
        logger.error(f"Failed to create feed entries for post {instance.id}: {e}")


def _create_post_feed_entries(post):
    hub_ids = list(post.unified_document.hubs.values_list("id", flat=True))
    transaction.on_commit(
        lambda: create_feed_entry.apply_async(
            args=(
                post.id,
                ContentType.objects.get_for_model(post).id,
                FeedEntry.PUBLISH,
                hub_ids,
                post.created_by.id,
            ),
            priority=1,
        )
    )
