from django.db.models.signals import post_save
from django.dispatch import receiver

from note.models import Note, NoteContent
from note.services.note_events import NoteVersionEventPublisher


@receiver(post_save, sender=NoteContent, dispatch_uid="update_latest_version")
def update_latest_version(sender, instance, created, update_fields, **kwargs):
    if created:
        source = instance.note
        Note.objects.filter(id=source.id).update(latest_version=instance)


# post_save on NoteContent is the one choke point every version writer passes
# through, so emitting here covers editor autosave, agent tools, and system
# writers alike. The publish itself is post-commit and best-effort.
_version_event_publisher = NoteVersionEventPublisher()


@receiver(post_save, sender=NoteContent, dispatch_uid="emit_note_version_created")
def emit_note_version_created(sender, instance, created, **kwargs):
    if created:
        _version_event_publisher.publish_created(instance)
