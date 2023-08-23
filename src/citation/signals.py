from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from .models import CitationProject


@receiver(post_save, sender=CitationProject, dispatch_uid="add_folder_slug")
def add_folder_slug(sender, instance, created, update_fields, **kwargs):
    if created:
        suffix = get_random_string(length=32)
        slug = slugify(instance.project_name)
        if not slug:
            slug += suffix
        if not CitationProject.objects.filter(slug=slug).exists():
            instance.slug = slug
        else:
            instance.slug = slug + "_" + suffix
        instance.save()
