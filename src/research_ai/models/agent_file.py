from django.db import models

from research_ai.models.agent import AgentConversation, AgentConversationMessage
from utils.models import DefaultModel


class AgentFile(DefaultModel):
    """A document a user uploaded to the private bucket for Research AI chats.

    Created unattached when the upload starts; sending a chat message with it
    attaches it to that message. Rows are hard-deleted along with their object:
    the extracted text is user content, not audit data. Only the purge deletes
    rows, so no relation cascades here: a row is the one record of its object.
    """

    class Status(models.TextChoices):
        UPLOADING = "UPLOADING", "Uploading"
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(
        "user.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="research_ai_files",
        db_comment=(
            "The uploader; null once they removed the file or their account, "
            "which leaves the row for the purge."
        ),
    )
    conversation = models.ForeignKey(
        AgentConversation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
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
    etag = models.CharField(
        max_length=128,
        blank=True,
        db_comment="ETag of the completed object; overwriting the object changes it.",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.UPLOADING
    )
    processing_started_date = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="When a worker picked the file up; null while it is queued.",
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
    pages_without_text = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_comment=(
            "PDF pages left without readable text (scans or figures no OCR "
            "read); null for other formats and files processed before this "
            "was recorded."
        ),
    )

    class Meta:
        db_table = "research_ai_agent_file"
