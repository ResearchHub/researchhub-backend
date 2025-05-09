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
                    score=instance.score,
                )
                unified_doc.hubs.add(*instance.hubs.all())
                instance.unified_document = unified_doc
                instance.save()
            except Exception as e:
                log_error("EXCPETION (add_unified_doc): ", e)
