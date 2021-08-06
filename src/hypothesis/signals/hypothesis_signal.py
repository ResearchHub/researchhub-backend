from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.crypto import get_random_string

from hypothesis.models import Hypothesis


@receiver(post_save, sender=Hypothesis, dispatch_uid='add_hypothesis_slug')
def add_hypothesis_slug(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if created:
        suffix = get_random_string(length=32)
        slug = slugify(instance.title)
        if not slug:
            slug += suffix
        instance.slug = slug
        instance.save()
