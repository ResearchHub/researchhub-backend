
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from feed.models import FeedEntry
from feed.tasks import create_feed_entry, delete_feed_entry
from django.db import transaction

"""
Signal handlers for Comment model.

The signal handlers are responsbile for creating and deleting feed entries
when comments are created and removed, respectively.
"""

@receiver(post_save, sender=RhCommentModel)
def handle_comment_created_or_removed(sender, instance, created, **kwargs):
    """
    When a comment is created or removed, create or delete a feed entry.
    """
    comment = instance
    
    if created:
        _handle_comment_created(comment)
    elif comment.is_removed:
        _handle_comment_removed(comment)

    
def _handle_comment_created(comment):
    tasks = [
        create_feed_entry.apply_async(
            args=(
                comment.id,
                ContentType.objects.get_for_model(comment).id,
                FeedEntry.PUBLISH,
                hub.id,
                ContentType.objects.get_for_model(hub).id,
                comment.created_by.id,
            ),
            priority=1,
        )
        for hub in comment.unified_document.hubs.all()
    ]
    transaction.on_commit(lambda: [task() for task in tasks])

def _handle_comment_removed(comment):
    tasks = [
        delete_feed_entry.apply_async(
            args=(
                comment.id,
                ContentType.objects.get_for_model(comment).id,
                hub.id,
                ContentType.objects.get_for_model(hub).id,
            ),
            priority=1,
        )
        for hub in comment.unified_document.hubs.all()
    ]
    transaction.on_commit(lambda: [task() for task in tasks])