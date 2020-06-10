from django.db.models.signals import post_save
from django.dispatch import receiver

from purchase.models import Purchase


@receiver(post_save, sender=Purchase, dispatch_uid='generate_purchase_hash')
def generate_purchase_hash(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if created:
        purchase_hash = instance.hash()
        instance.purchase_hash = purchase_hash
        instance.save()
