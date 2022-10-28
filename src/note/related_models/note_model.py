from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models

from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Organization, User
from utils.models import DefaultModel


class Note(DefaultModel):
    created_by = models.ForeignKey(
        User, null=True, related_name="created_notes", on_delete=models.SET_NULL
    )
    latest_version = models.ForeignKey(
        "note.NoteContent", null=True, related_name="source", on_delete=models.CASCADE
    )
    organization = models.ForeignKey(
        Organization, null=True, related_name="created_notes", on_delete=models.SET_NULL
    )
    title = models.TextField(blank=True, default="")
    unified_document = models.OneToOneField(
        ResearchhubUnifiedDocument, related_name="note", on_delete=models.CASCADE
    )

    def __str__(self):
        return f"Id: {self.id}, Title: {self.title}"

    @property
    def permissions(self):
        return self.unified_document.permissions

    @property
    def owner(self):
        pass

    def notify_note_created(self):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()
        # async_to_sync(channel_layer.group_send)(
        #     room,
        #     {
        #         "type": "notify_note_created",
        #         "id": self.id,
        #     },
        # )

    def notify_note_deleted(self):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()
        # async_to_sync(channel_layer.group_send)(
        #     room,
        #     {
        #         "type": "notify_note_deleted",
        #         "id": self.id,
        #     },
        # )

    def notify_note_updated_title(self):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()
        # async_to_sync(channel_layer.group_send)(
        #     room,
        #     {
        #         "type": "notify_note_updated_title",
        #         "id": self.id,
        #     },
        # )

    def notify_note_updated_permission(self, requester):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()
        # async_to_sync(channel_layer.group_send)(
        #     room,
        #     {
        #         "type": "notify_note_updated_permission",
        #         "id": self.id,
        #         "requester_id": requester.id,
        #     },
        # )


class NoteContent(models.Model):
    created_date = models.DateTimeField(auto_now_add=True)
    note = models.ForeignKey(Note, related_name="notes", on_delete=models.CASCADE)
    plain_text = models.TextField(null=True)
    src = models.FileField(
        max_length=512,
        upload_to="note/uploads/%Y/%m/%d",
        default=None,
        null=True,
        blank=True,
    )
