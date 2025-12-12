import logging

from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from personalize.tasks import sync_unified_document_to_personalize_task
from researchhub_document.models import ResearchhubUnifiedDocument

logger = logging.getLogger(__name__)


@receiver(
    m2m_changed,
    sender=ResearchhubUnifiedDocument.hubs.through,
    dispatch_uid="sync_unified_doc_to_personalize_on_hubs_change",
)
def sync_unified_document_to_personalize(sender, instance, action, pk_set, **kwargs):
    """
    Sync unified documents to AWS Personalize when hubs change.

    Triggers on post_add, post_remove, and post_clear to keep Personalize
    in sync with the current hub state.

    The task handles additional filtering (e.g., paper recency check).
    """
    # Only trigger after changes are committed (skip pre_* actions)
    if not action.startswith("post"):
        return

    # Only trigger when hubs change on a unified document (not the reverse)
    if not isinstance(instance, ResearchhubUnifiedDocument):
        return

    try:
        sync_unified_document_to_personalize_task.delay(instance.id)
    except Exception as e:
        logger.error(
            f"Failed to queue personalize sync for unified_document {instance.id}: {e}"
        )
