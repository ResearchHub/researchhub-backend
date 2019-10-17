from django.core.signals import post_save
from django.dispatch import receiver

from .distributor import Distributor
from .distributions import CreatePaper


@receiver(post_save, sender='paper.Paper')
def distribute_create_paper_issuance(sender, request, **kwargs):
    distributor = Distributor(CreatePaper, request, sender)
    distributor.distribute()
