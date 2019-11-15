from django.db.models.signals import post_save
from django.dispatch import receiver

from search.plugins import pdf_pipeline
from paper.models import Paper


@receiver(post_save, sender=Paper, dispatch_uid='update_paper')
def attach_file_to_document(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if not created and check_file_updated(update_fields):
        response = pdf_pipeline.attach_pdf_to_document(
            'paper',
            instance
        )
        return response.ok


def check_file_updated(update_fields):
    if update_fields is not None:
        return 'file' in update_fields
    return False
