import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.tasks import publish_to_feed
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
    if instance.document_type == GRANT or not instance.unified_document.is_approved:
        return

    try:
        _create_post_feed_entries(instance)
    except Exception:
        logger.exception("Failed to create feed entries for post %s", instance.id)


def _create_post_feed_entries(post):
    publish_to_feed(post, post.created_by_id)
