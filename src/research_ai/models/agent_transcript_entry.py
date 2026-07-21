from django.db import models

from utils.models import DefaultModel

from .agent_conversation import AgentConversation
from .agent_run import AgentRun


class AgentTranscriptEntry(DefaultModel):
    """One ordered provider-context entry in an agent conversation.

    This is the internal model/tool transcript, not the product chat record.
    User-facing messages live in ``AgentChatMessage`` and may point back to the
    transcript entry from which they were derived.

    Rows are append-only. Anything that changes future model context is
    represented by another entry, and the provider context is rebuilt by
    ``agent_transcript.build_context``.
    """

    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    class Source(models.TextChoices):
        """Who authored the entry as it was sent to the model."""

        HUMAN = "human"
        BACKEND = "backend"
        TOOL = "tool"
        AGENT = "agent"

    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        related_name="transcript_entries",
    )
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="transcript_entries",
    )
    sequence = models.PositiveIntegerField(
        db_comment=(
            "Per-conversation transcript position, allocated under a "
            "conversation row lock."
        ),
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        db_comment=(
            "Provenance of the provider-context entry: human chat input, a "
            "backend-composed prompt, tool results, or the agent itself."
        ),
    )
    content = models.JSONField(
        db_comment=(
            "The serialized provider-neutral block list. The block vocabulary "
            "is additive; consumers must tolerate unrecognized block types."
        ),
    )
    meta = models.JSONField(
        null=True,
        blank=True,
        db_comment="Internal annotations that are not provider content blocks.",
    )
    # Per-model-turn metadata, populated on assistant entries only.
    input_tokens = models.BigIntegerField(null=True, blank=True)
    output_tokens = models.BigIntegerField(null=True, blank=True)
    cache_read_tokens = models.BigIntegerField(null=True, blank=True)
    cache_write_tokens = models.BigIntegerField(null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    stop_reason = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "research_ai_agent_transcript_entry"
        ordering = ["conversation", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"],
                name="research_ai_ate_conv_seq_unique",
            ),
        ]

    def __str__(self):
        return f"AgentTranscriptEntry {self.id} ({self.role} #{self.sequence})"
