from django.db.models.signals import post_save
from django.dispatch import receiver

from reputation.models import Contribution
from reputation.tasks import create_contribution
from researchhub_document.models import ResearchhubPost


@receiver(
    post_save,
    sender=ResearchhubPost,
    dispatch_uid="rh_post_create_contribution",
)
def rh_post_create_contribution(created, instance, sender, update_fields, **kwargs):
    if created:
        created_by = instance.created_by
        unified_doc_id = instance.unified_document.id
        create_contribution.apply_async(
            (
                Contribution.SUBMITTER,
                {"app_label": "researchhub_document", "model": "researchhubpost"},
                created_by.id,
                unified_doc_id,
                instance.id,
            ),
            priority=3,
            countdown=5,
        )
