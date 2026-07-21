from django.db import models

from utils.models import DefaultModel


class AgentChatMessage(DefaultModel):
    """A user-facing message in an agent conversation.

    Chat messages are product records. They intentionally remain separate from
    the internal provider/tool transcript so retries, prompt templating, and
    telemetry retention do not duplicate or rewrite what the user sees.
    """

    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(
        "research_ai.AgentConversation",
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    sequence = models.PositiveIntegerField(
        db_comment="Independent position in the user-facing conversation.",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.JSONField(
        db_comment="Structured content rendered by the product chat interface.",
    )
    produced_by_run = models.ForeignKey(
        "research_ai.AgentRun",
        on_delete=models.SET_NULL,
        related_name="output_chat_messages",
        null=True,
        blank=True,
        db_comment="Execution that produced an assistant message; null for users.",
    )
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="replies",
        null=True,
        blank=True,
    )
    transcript_entry = models.OneToOneField(
        "research_ai.AgentTranscriptEntry",
        on_delete=models.SET_NULL,
        related_name="chat_message",
        null=True,
        blank=True,
        db_comment="Internal transcript entry from which this message was derived.",
    )

    class Meta:
        db_table = "research_ai_agent_chat_message"
        ordering = ["conversation", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"],
                name="research_ai_acm_conv_seq_unique",
            ),
        ]

    def __str__(self):
        return f"AgentChatMessage {self.id} ({self.role} #{self.sequence})"
