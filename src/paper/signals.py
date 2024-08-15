from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from paper.related_models.authorship_model import Authorship
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
    if instance.work_type not in ["preprint", "article"]:
        return
    authorships = Authorship.objects.filter(paper=instance).select_related("author")

    for authorship in authorships:
        instance.update_scores_citations(
            authorship.author,
        )


@receiver(post_save, sender=Authorship, dispatch_uid="update_rep_score_authorship")
def update_rep_score_authorship(created, instance, update_fields, **kwargs):
    if created:
        paper = instance.paper
        if paper is None:
            return

        author = instance.author
        paper.update_scores_citations(author)


@receiver(
    post_delete, sender=Authorship, dispatch_uid="update_rep_score_authorship_delete"
)
def update_rep_score_authorship_delete(instance, **kwargs):
    paper = instance.paper
    if paper is None:
        return

    author = instance.author
    paper.update_scores_citations(author)


def check_file_updated(update_fields, file):
    if update_fields is not None and file:
        return "file" in update_fields
    return False
