from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

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


@receiver(post_save, sender=Paper, dispatch_uid="update_rep_score")
def update_rep_score(created, instance, update_fields, **kwargs):
    authors = instance.authors.all()
    historical_paper = instance.history.all().order_by("history_date").latest()
    previous_historical_paper = historical_paper.prev_record
    unified_doc = instance.unified_document
    if unified_doc is None:
        print(f"Paper {instance.id} has no unified document")
        return

    hub = unified_doc.get_primary_hub()
    if hub is None:
        print(f"Paper {instance.id} has no primary hub")
        return

    for author in authors:
        author.update_scores_citation(
            historical_paper,
            previous_historical_paper,
            hub,
        )


def check_file_updated(update_fields, file):
    if update_fields is not None and file:
        return "file" in update_fields
    return False
