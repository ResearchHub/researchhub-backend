import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from paper.models import Paper
from personalize.tasks import sync_paper_to_personalize_task

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Paper)
def sync_paper_to_personalize(sender, instance, created, **kwargs):
    if not created:
        return

    paper = instance

    if not paper.unified_document:
        return

    sync_paper_to_personalize_task.delay(paper.id)
