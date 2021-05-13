from django.db.models.signals import post_save
from django.dispatch import receiver

from search.plugins import pdf_pipeline
from paper.models import Paper
from utils import sentry


@receiver(post_save, sender=Paper, dispatch_uid='update_paper')
def attach_file_to_document(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if not created and check_file_updated(update_fields):
        try:
            if instance.file is not None:
                response = pdf_pipeline.attach_paper_pdf(instance)
                return response.ok
        except Exception as e:
            sentry.log_error(
                e,
                'Failed to attach file to document'
            )


def check_file_updated(update_fields):
    if update_fields is not None:
        return 'file' in update_fields
    return False
