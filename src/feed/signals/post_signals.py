import logging
from functools import partial

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.tasks import create_feed_entry, delete_feed_entry
from hub.models import Hub
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

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


@receiver(
    post_save, sender=ResearchhubUnifiedDocument, dispatch_uid="post_delete_feed_entry"
)
def handle_post_delete_feed_entry(sender, instance, **kwargs):
    """
    When a post is deleted, delete feed entries for all hubs associated with the
    researchhub document that the post is associated with.
    """
    try:
        _delete_post_feed_entries(instance)
    except Exception as e:
        logger.error(
            f"Failed to delete feed entries for unified document {instance.id}: {e}"
        )


@receiver(
    m2m_changed,
    sender=ResearchhubUnifiedDocument.hubs.through,
    dispatch_uid="post_hubs_changed",
)
def handle_post_hubs_changed(sender, instance, action, pk_set, **kwargs):
    """
    Create or delete feed entries when a hub is added or removed from a unified
    document that is associated with a post.
    """
    try:
        if action == "post_add":
            _handle_post_hubs_added(instance, pk_set)
        elif action == "pre_remove":
            _handle_post_hubs_removed(instance, pk_set)
    except Exception as e:
        action_type = "add" if action == "post_add" else "remove"
        logger.error(f"Failed to {action_type} post hubsfor {instance.id}: {e}")


def _create_post_feed_entries(post):
    tasks = [
        partial(
            create_feed_entry.apply_async,
            args=(
                post.id,
                ContentType.objects.get_for_model(post).id,
                FeedEntry.PUBLISH,
                hub.id,
                ContentType.objects.get_for_model(hub).id,
                post.created_by.id,
            ),
            priority=1,
        )
        for hub in post.unified_document.hubs.all()
    ]
    transaction.on_commit(lambda: [task() for task in tasks])


def _delete_post_feed_entries(unified_document):
    if (
        unified_document.document_type == document_type.DISCUSSION
        and unified_document.is_removed == True
    ):
        posts = unified_document.posts.all()
        hubs = unified_document.hubs.all()

        tasks = [
            partial(
                delete_feed_entry.apply_async,
                args=(
                    post.id,
                    ContentType.objects.get_for_model(post).id,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
            for post in posts
            for hub in hubs
        ]
        transaction.on_commit(lambda: [task() for task in tasks])


def _handle_post_hubs_added(instance, pk_set):
    for entity_id in pk_set:
        if isinstance(instance, ResearchhubUnifiedDocument):
            unified_document = instance
            hub = unified_document.hubs.get(id=entity_id)
        elif isinstance(instance, Hub):
            hub = instance
            unified_document = hub.related_documents.get(id=entity_id)
        else:
            continue

        # Create feed entries for all posts associated with this unified document
        for post in unified_document.posts.all():
            create_feed_entry.apply_async(
                args=(
                    post.id,
                    ContentType.objects.get_for_model(post).id,
                    "PUBLISH",
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )


def _handle_post_hubs_removed(instance, pk_set):
    for entity_id in pk_set:
        if isinstance(instance, ResearchhubUnifiedDocument):
            unified_document = instance
            hub = unified_document.hubs.get(id=entity_id)
        elif isinstance(instance, Hub):
            hub = instance
            unified_document = hub.related_documents.get(id=entity_id)
        else:
            continue

        # Delete feed entries for all posts associated with this unified document
        for post in unified_document.posts.all():
            delete_feed_entry.apply_async(
                args=(
                    post.id,
                    ContentType.objects.get_for_model(post).id,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
