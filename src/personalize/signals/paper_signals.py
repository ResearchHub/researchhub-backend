import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from paper.models import Paper
from personalize.tasks import sync_paper_to_personalize_task

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Paper)
def sync_paper_to_personalize(sender, instance, created, **kwargs):
    print(
        f"[PERSONALIZE SIGNAL] sync_paper_to_personalize called with paper_id={instance.id}, created={created}"
    )
    if not created:
        return

    paper = instance

    if not paper.unified_document:
        logger.warning(
            f"Paper {paper.id} created without unified_document, skipping Personalize sync"
        )
        return

    logger.info(f"Queueing paper {paper.id} for Personalize sync")

    sync_paper_to_personalize_task.delay(paper.id)
