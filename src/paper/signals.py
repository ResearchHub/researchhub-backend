from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from feed.models import create_feed_entry, delete_feed_entry
from hub.models import Hub
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    PAPER as PAPER_DOC_TYPE,
)
from utils.sentry import log_error

from .models import Paper


@receiver(post_save, sender=Paper, dispatch_uid="add_paper_slug")
def add_paper_slug(sender, instance, created, update_fields, **kwargs):
    if created:
        suffix = get_random_string(length=32)
        paper_title = instance.paper_title
        title = instance.title

        slug = paper_title or title
        slug = slugify(slug)
        if not slug:
            slug += suffix
        instance.slug = slug
        instance.save()


@receiver(post_save, sender=Paper, dispatch_uid="add_unified_doc")
def add_unified_doc(created, instance, **kwargs):
    if created:
        unified_doc = ResearchhubUnifiedDocument.objects.filter(
            paper__id=instance.id
        ).first()
        if unified_doc is None:
            try:
                unified_doc = ResearchhubUnifiedDocument.objects.create(
                    document_type=PAPER_DOC_TYPE,
                    hot_score=instance.calculate_hot_score(),
                    score=instance.score,
                )
                unified_doc.hubs.add(*instance.hubs.all())
                instance.unified_document = unified_doc
                instance.save()
            except Exception as e:
                log_error("EXCPETION (add_unified_doc): ", e)


@receiver(m2m_changed, sender=Paper.hubs.through, dispatch_uid="paper_hubs_changed")
def handle_paper_hubs_changed(sender, instance, action, pk_set, **kwargs):
    if action == "post_add":
        for hub_id in pk_set:
            if isinstance(instance, Paper):
                hub = instance.hubs.get(id=hub_id)
                paper = instance
            else:  # instance is Hub
                hub = instance
                paper = hub.papers.get(id=hub_id)

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
        for hub_id in pk_set:
            if isinstance(instance, Paper):
                hub = Hub.objects.get(id=hub_id)
                paper = instance
            else:  # instance is Hub
                hub = instance
                paper = Paper.objects.get(id=hub_id)

            if paper.paper_publish_date is None:
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


def check_file_updated(update_fields, file):
    if update_fields is not None and file:
        return "file" in update_fields
    return False
