from django.db import models

from utils.models import DefaultModel

from .agent_conversation import AgentConversation
from .agent_run import AgentRun


class AgentMessage(DefaultModel):
    """
    One conversation ``Message``, in order -- an append-only log.

    Rows are never updated or deleted by application code; anything that should
    change what the model later sees is expressed as new rows, and the provider
    context is derived from the log (see ``agent_transcript.build_context``).
    """

    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sequence = models.PositiveIntegerField(
        db_comment=(
            "Per-conversation position, allocated under a conversation row lock."
        ),
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.JSONField(
        db_comment=(
            "The exact serialize_messages block list. The block vocabulary is "
            "additive: consumers must route on `type` and tolerate types they "
            "don't recognize."
        ),
    )
    meta = models.JSONField(
        null=True,
        blank=True,
        db_comment=(
            "Message-level annotations that are not content blocks (kept "
            "separate so `content` stays exactly the wire shape). Empty in v1."
        ),
    )
    # Per-turn metadata, assistant rows only. Columns (not JSON) so they
    # aggregate in SQL; null when the provider did not report a counter.
    input_tokens = models.BigIntegerField(null=True, blank=True)
    output_tokens = models.BigIntegerField(null=True, blank=True)
    cache_read_tokens = models.BigIntegerField(null=True, blank=True)
    cache_write_tokens = models.BigIntegerField(null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    stop_reason = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "research_ai_agent_message"
        ordering = ["conversation", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"],
                name="research_ai_am_conv_seq_unique",
            ),
        ]

    def __str__(self):
        return f"AgentMessage {self.id} ({self.role} #{self.sequence})"
