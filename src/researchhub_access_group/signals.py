from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string

from researchhub_access_group.models import ResearchhubAccessGroup


@receiver(
    pre_save,
    sender=ResearchhubAccessGroup,
    dispatch_uid='add_meta_data'
)
def add_meta_data(
    sender,
    instance,
    update_fields,
    **kwargs
):
    if not instance.key:
        key = get_random_string(length=32)
        instance.key = key

    if not instance.name:
        name = get_random_string(length=32)
        instance.name = name
