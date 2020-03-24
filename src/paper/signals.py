from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Paper
@receiver(post_save, sender=Paper, dispatch_uid='pdf_extract_figures')
def queue_extract_figures_from_pdf(sender, instance, created, **kwargs):
    if not created and instance.file and not instance.figures.all():
        instance.extract_pdf_preview(use_celery=True)
        instance.extract_figures(use_celery=True)
