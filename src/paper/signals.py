from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Paper
@receiver(post_save, sender=Paper, dispatch_uid='pdf_extract_figures')
def queue_extract_figures_from_pdf(sender, instance, created, **kwargs):
    if created:
        instance.extract_pdf_preview()
        instance.extract_figures()
