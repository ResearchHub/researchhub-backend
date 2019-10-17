from time import time

from django.db.models.signals import post_save
from django.dispatch import receiver

from .distributor import Distributor
from .distributions import CreatePaper

from paper.models import Paper


@receiver(post_save, sender=Paper, dispatch_uid='create_paper_issuance')
def distribute_create_paper_distribution(sender, instance, created, **kwargs):
    timestamp = time()
    if created and instance.uploaded_by:
        distributor = Distributor(
            CreatePaper,
            instance.uploaded_by,
            instance,
            timestamp
        )
        distributor.distribute()
