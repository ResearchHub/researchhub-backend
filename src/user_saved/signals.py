"""
Signal handlers for user saved lists
"""

from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

from .models import UserSavedEntry


@receiver(pre_delete, sender=ResearchhubUnifiedDocument)
def handle_document_deletion(sender, instance, **kwargs):
    """
    When a unified document is deleted, mark all related user saved entries
    as having deleted documents and preserve snapshot information
    """
    # Find all user saved entries that reference this document
    entries = UserSavedEntry.objects.filter(unified_document=instance, is_removed=False)

    # Update each entry to mark the document as deleted
    for entry in entries:
        entry.document_deleted = True
        entry.document_deleted_date = timezone.now()
        # Keep the unified_document reference for now, it will be set to None
        # when the document is actually deleted due to CASCADE behavior
        entry.save()

    # Now set the unified_document to None to preserve the entry
    # but remove the foreign key reference
    entries.update(unified_document=None)
