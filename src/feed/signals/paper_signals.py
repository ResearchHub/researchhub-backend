from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from feed.tasks import create_feed_entry, delete_feed_entry
from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

"""
Signal handlers for Paper model.

The signal handlers are responsible for creating and deleting feed entries
when papers are added to or removed from hubs.
"""


@receiver(
    m2m_changed,
    sender=ResearchhubUnifiedDocument.hubs.through,
    dispatch_uid="unified_doc_hubs_changed",
)
def handle_unified_doc_hubs_changed(sender, instance, action, pk_set, **kwargs):
    if action == "post_add":
        for entity_id in pk_set:
            if (
                isinstance(instance, ResearchhubUnifiedDocument)
                and instance.document_type == "PAPER"
            ):
                hub = instance.hubs.get(id=entity_id)
                paper = instance.paper
            elif isinstance(instance, Hub):  # instance is Hub
                hub = instance
                paper = hub.related_documents.get(id=entity_id).paper
            else:
                continue

            # We order feed entries by publish date, so we don't need to
            # create feed entries for papers that don't have a publish date
            if paper.paper_publish_date is None:
                continue

            create_feed_entry.apply_async(
                args=(
                    paper.id,
                    ContentType.objects.get_for_model(paper).id,
                    "PUBLISH",
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
    elif action == "post_remove":
        for entity_id in pk_set:
            if (
                isinstance(instance, ResearchhubUnifiedDocument)
                and instance.document_type == "PAPER"
            ):
                hub = Hub.objects.get(id=entity_id)
                paper = instance.paper
            elif isinstance(instance, Hub):  # instance is Hub
                hub = instance
                paper = hub.related_documents.get(id=entity_id).paper
            else:
                continue

            delete_feed_entry.apply_async(
                args=(
                    paper.id,
                    ContentType.objects.get_for_model(paper).id,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
