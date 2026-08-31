import json

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models

from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import DOCUMENT_TYPES
from user.models import Organization, User
from utils.models import DefaultModel


class Note(DefaultModel):
    created_by = models.ForeignKey(
        User, null=True, related_name="created_notes", on_delete=models.SET_NULL
    )
    document_type = models.CharField(
        choices=DOCUMENT_TYPES,
        max_length=32,
        null=True,
        blank=True,
    )
    image = models.TextField(
        blank=True,
        null=True,
    )
    latest_version = models.ForeignKey(
        "note.NoteContent", null=True, related_name="source", on_delete=models.CASCADE
    )
    organization = models.ForeignKey(
        Organization, null=True, related_name="created_notes", on_delete=models.SET_NULL
    )
    preview_img = models.URLField(
        blank=True,
        max_length=2048,
        null=True,
    )
    selected_grant = models.ForeignKey(
        "purchase.Grant",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="draft_notes",
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

    def _get_serialized_notification_data(self):
        from note.serializers import NoteSerializer

        return NoteSerializer(self).data

    def notify_note_created(self):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()

        serialized_data = self._get_serialized_notification_data()
        data = {
            "type": "create",
            "data": serialized_data,
        }
        async_to_sync(channel_layer.group_send)(
            room, {"type": "send_note_notification", "data": data}
        )

    def notify_note_deleted(self):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()
        serialized_data = self._get_serialized_notification_data()
        data = {
            "type": "delete",
            "data": serialized_data,
        }
        async_to_sync(channel_layer.group_send)(
            room,
            {
                "type": "send_note_notification",
                "data": data,
            },
        )

    def notify_note_updated_title(self):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()
        serialized_data = self._get_serialized_notification_data()
        data = {
            "type": "update_title",
            "data": serialized_data,
        }
        async_to_sync(channel_layer.group_send)(
            room,
            {
                "type": "send_note_notification",
                "data": data,
            },
        )

    def notify_note_updated_permission(self, requester):
        organization_slug = self.organization.slug
        room = f"{organization_slug}_notebook"
        channel_layer = get_channel_layer()
        serialized_data = self._get_serialized_notification_data()
        data = {
            "type": "update_permission",
            "data": serialized_data,
        }

        async_to_sync(channel_layer.group_send)(
            room,
            {
                "type": "send_note_notification",
                "data": data,
                "requester_id": requester.id,
            },
        )


def parse_note_json(value: object) -> dict[str, object] | None:
    """Parse a ``NoteContent.json``-style value (dict or JSON-encoded string)."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


class NoteContent(models.Model):
    # created_via values; null means unknown (legacy rows).
    CREATED_VIA_EDITOR = "editor"
    CREATED_VIA_AGENT = "agent"
    CREATED_VIA_SYSTEM = "system"
    CREATED_VIA_CHOICES = [
        (CREATED_VIA_EDITOR, CREATED_VIA_EDITOR),
        (CREATED_VIA_AGENT, CREATED_VIA_AGENT),
        (CREATED_VIA_SYSTEM, CREATED_VIA_SYSTEM),
    ]

    created_date = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="created_note_versions",
        on_delete=models.SET_NULL,
    )
    created_via = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        choices=CREATED_VIA_CHOICES,
    )
    note = models.ForeignKey(Note, related_name="notes", on_delete=models.CASCADE)
    # The version this one was derived from (advisory; null for legacy rows
    # and writers that do not track a base).
    parent_version = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="derived_versions",
        on_delete=models.SET_NULL,
    )
    plain_text = models.TextField(null=True)
    src = models.FileField(
        max_length=512,
        upload_to="note/uploads/%Y/%m/%d",
        default=None,
        null=True,
        blank=True,
    )
    json = models.JSONField(null=True, blank=True)
