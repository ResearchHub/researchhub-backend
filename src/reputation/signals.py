from django.db.models.signals import post_save
from django.dispatch import receiver

from .distributor import Distributor
from .distributions import CreatePaper

from paper.models import Paper


@receiver(post_save, sender=Paper)
def distribute_create_paper_issuance(sender, instance, created, **kwargs):
    if created and instance.uploaded_by:
        distributor = Distributor(CreatePaper, instance.uploaded_by, instance)
        distributor.distribute()
