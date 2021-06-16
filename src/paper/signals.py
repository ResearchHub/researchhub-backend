from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.crypto import get_random_string

from .models import Paper, Vote
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    PAPER
)


@receiver(post_save, sender=Paper, dispatch_uid='add_paper_slug')
def add_paper_slug(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
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


@receiver(post_save, sender=Paper, dispatch_uid='add_unified_doc')
def add_unified_doc(created, instance, **kwargs):
    if created:
        unified_doc = ResearchhubUnifiedDocument.objects.filter(
            paper__id=instance.id
        ).first()
        if unified_doc is None:
            try:
                curr_hot_score = instance.calculate_hot_score()
                curr_score = instance.calculate_score()
                rh_unified_doc = ResearchhubUnifiedDocument.objects.create(
                    document_type=PAPER,
                    hot_score=0 if curr_hot_score is None else curr_hot_score,
                    paper=instance,
                    score=0 if curr_score is None else curr_score
                )
                hubs = instance.hubs.all()
                rh_unified_doc.hubs.add(*hubs)
                rh_unified_doc.save()
            except Exception as e:
                print("EXCPETION (add_unified_doc): ", e)


@receiver(post_save, sender=Vote, dispatch_uid='recalculate_paper_votes')
def recalc_paper_votes(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    paper = instance.paper
    new_score = paper.calculate_score()
    paper.calculate_hot_score()
    paper.score = new_score
    for author in paper.authors.all():
        score = author.calculate_score()
        author.author_score = score
        author.save()
    paper.save()


def check_file_updated(update_fields, file):
    if update_fields is not None and file:
        return 'file' in update_fields
    return False
