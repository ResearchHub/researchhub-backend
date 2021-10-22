from django.db.models.signals import post_save
from django.dispatch import receiver

from note.models import Note, NoteContent


@receiver(post_save, sender=NoteContent, dispatch_uid='update_latest_version')
def update_latest_version(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if created:
        source = instance.note
        Note.objects.filter(
            id=source.id
        ).update(
            latest_version=instance
        )
