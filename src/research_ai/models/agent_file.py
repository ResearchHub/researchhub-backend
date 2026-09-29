from django.db import models

from research_ai.models.agent import AgentConversation, AgentConversationMessage
from utils.models import DefaultModel


class AgentFile(DefaultModel):
    """A document a user uploaded to the private bucket for Research AI chats.

    Created unattached when the upload starts; sending a chat message with it
    attaches it to that message. Rows are hard-deleted along with their object:
    the extracted text is user content, not audit data.
    """

    class Status(models.TextChoices):
        UPLOADING = "UPLOADING", "Uploading"
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(
        "user.User",
        on_delete=models.CASCADE,
        related_name="research_ai_files",
    )
    conversation = models.ForeignKey(
        AgentConversation,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="files",
        db_comment="Set when the file is attached to a message in this conversation.",
    )
    message = models.ForeignKey(
        AgentConversationMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments",
        db_comment="The user message the file was sent with; null until then.",
    )
    filename = models.CharField(max_length=255)
    content_type = models.CharField(
        max_length=128,
        db_comment="Canonical MIME type resolved from the upload; S3 enforces it.",
    )
    size_bytes = models.PositiveBigIntegerField()
    storage_key = models.CharField(max_length=512, unique=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.UPLOADING
    )
    error = models.CharField(
        max_length=255,
        blank=True,
        db_comment="User-safe reason the file could not be processed.",
    )
    text = models.TextField(
        blank=True, db_comment="Text extracted for the agent to read."
    )
    text_truncated = models.BooleanField(default=False)
    page_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "research_ai_agent_file"
