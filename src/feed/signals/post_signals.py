import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import GRANT

"""
Signal handlers for ResearchhubPost model.

The signal handlers are responsbile for creating and deleting feed entries
when posts are created and deleted, respectively.

A post is created after hubs are added to the unified document that the post is associated with
so we need to create a feed entry for the post when it is created instead.

Posts awaiting moderator approval skip feed entry creation here; they get
entries once approved. This covers Grants (published on grant approval) and any
post whose moderation status isn't APPROVED.
"""

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ResearchhubPost, dispatch_uid="post_create_feed_entry")
def handle_post_create_feed_entry(sender, instance, **kwargs):
    """Create feed entries for a new post, unless it's awaiting approval.

    Grants are deferred to grant approval, and any post that isn't APPROVED is
    deferred to content moderation; both get their feed entries on approval.
    """
    if instance.document_type == GRANT or not instance.is_approved:
        return

    try:
        _create_post_feed_entries(instance)
    except Exception:
        logger.exception("Failed to create feed entries for post %s", instance.id)


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
