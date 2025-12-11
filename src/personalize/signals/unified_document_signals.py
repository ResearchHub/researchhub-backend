from django.db.models.signals import post_save
from django.dispatch import receiver

from personalize.tasks import sync_unified_document_to_personalize_task
from researchhub_document.models import ResearchhubUnifiedDocument


@receiver(post_save, sender=ResearchhubUnifiedDocument)
def sync_unified_document_to_personalize(sender, instance, created, **kwargs):
    """
    Queue sync of newly created unified documents to AWS Personalize.

    The task handles filtering logic (e.g., paper recency check).
    """
    if not created:
        return

    sync_unified_document_to_personalize_task.delay(instance.id)
