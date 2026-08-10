from django.core.exceptions import ValidationError
from django.db import models

from utils.models import DefaultModel


class AgentConversation(DefaultModel):
    """Durable grouping for related agent executions and user-visible turns."""

    user = models.ForeignKey(
        "user.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="research_ai_agent_conversations",
        db_index=False,
        db_comment="Owning user; null for headless workflows or deleted users.",
    )
    workflow = models.CharField(
        max_length=64,
        blank=True,
        db_comment=(
            "Stable identifier for the workflow that created the conversation, "
            "such as proposal_draft or notebook_chat."
        ),
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        db_comment=(
            "User-visible conversation name. Blank until the workflow derives "
            "one (typically from the first message) or the user sets it."
        ),
    )
    next_trace_sequence = models.PositiveBigIntegerField(default=1)
    next_chat_sequence = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "research_ai_agent_conversation"
        indexes = [
            models.Index(
                fields=["user", "updated_date"], name="ra_agent_conv_user_date"
            ),
            models.Index(fields=["workflow"], name="ra_agent_conv_workflow"),
        ]


class NoteAgentConversation(DefaultModel):
    """Attach an agent conversation to a notebook."""

    note = models.ForeignKey(
        "note.Note",
        on_delete=models.CASCADE,
        related_name="agent_conversation_links",
        db_index=False,
    )
    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        related_name="note_links",
    )

    class Meta:
        db_table = "research_ai_note_agent_conversation"
        constraints = [
            models.UniqueConstraint(
                fields=["note", "conversation"],
                name="ra_note_agent_conv_unique",
            )
        ]


class AgentExecution(DefaultModel):
    """One attempt to advance an :class:`AgentConversation`."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        INTERRUPTED = "INTERRUPTED", "Interrupted"
        CANCELLED = "CANCELLED", "Cancelled"

    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        related_name="executions",
        db_index=False,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempt = models.PositiveIntegerField()
    context_parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="continuations",
        db_comment=(
            "Prior execution whose durable context supplies this attempt's model "
            "context."
        ),
    )
    retry_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retries",
    )
    trigger_message = models.ForeignKey(
        "research_ai.AgentConversationMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="triggered_executions",
        db_comment="Canonical human message reused by retries and regenerations.",
    )
    provider = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=255, blank=True)
    configuration = models.JSONField(default=dict, blank=True)
    system_prompt = models.TextField(blank=True)
    final_output = models.JSONField(default=dict, blank=True)
    stop_reason = models.CharField(max_length=64, blank=True)
    error_type = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    error_details = models.JSONField(default=dict, blank=True)
    iterations = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    output_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cache_read_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cache_write_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    total_latency_ms = models.PositiveBigIntegerField(null=True, blank=True)
    duration_ms = models.PositiveBigIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    next_message_sequence = models.PositiveIntegerField(default=1)
    next_context_sequence = models.PositiveIntegerField(default=1)
    publish_output_to_chat = models.BooleanField(
        default=False,
        db_comment=(
            "Durable publication intent. A successful execution without a generated "
            "chat message remains eligible for repair."
        ),
    )
    replaces_output_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replacement_outputs",
        db_comment=(
            "Execution whose public assistant message this regeneration replaces."
        ),
    )

    class Meta:
        db_table = "research_ai_agent_execution"
        ordering = ["conversation_id", "attempt"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "attempt"], name="ra_agent_exec_attempt"
            ),
            models.UniqueConstraint(
                fields=["conversation"],
                condition=models.Q(status__in=["PENDING", "RUNNING"]),
                name="ra_agent_exec_one_active",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "started_at"], name="ra_agent_exec_status_at"
            ),
        ]


class AgentConversationMessage(DefaultModel):
    """Canonical user-facing chat content, independent from debug retention."""

    class Role(models.TextChoices):
        USER = "USER", "User"
        ASSISTANT = "ASSISTANT", "Assistant"

    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        related_name="chat_messages",
        db_index=False,
    )
    sequence = models.PositiveBigIntegerField()
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    generated_by_execution = models.OneToOneField(
        AgentExecution,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_chat_message",
    )
    in_reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "research_ai_agent_conversation_message"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"], name="ra_agent_chat_sequence"
            )
        ]
        indexes = [
            models.Index(
                fields=["conversation", "is_active", "sequence"],
                name="ra_agent_chat_visible",
            )
        ]


class AgentContextMessage(DefaultModel):
    """Durable, bounded model context kept independently from debug traces."""

    execution = models.ForeignKey(
        AgentExecution,
        on_delete=models.CASCADE,
        related_name="context_messages",
        db_index=False,
    )
    sequence = models.PositiveIntegerField()
    role = models.CharField(max_length=32)
    content = models.JSONField(default=list)
    provider_state = models.JSONField(default=dict)
    is_compacted = models.BooleanField(default=False)
    original_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "research_ai_agent_context_message"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "sequence"],
                name="ra_agent_context_sequence",
            )
        ]


class AgentExecutionMessage(DefaultModel):
    """One incrementally persisted model-protocol message in an execution trace.

    ``conversation`` is deliberately denormalized from ``execution`` to support
    conversation-wide ordering and uniqueness. Normal saves enforce that the
    two relationships agree. Bulk APIs bypass ``save()`` and must not be used to
    change either relationship.
    """

    class Provenance(models.TextChoices):
        HUMAN = "HUMAN", "Human"
        BACKEND = "BACKEND", "Backend"
        MODEL = "MODEL", "Model"
        TOOL = "TOOL", "Tool"

    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        related_name="trace_messages",
        db_index=False,
    )
    execution = models.ForeignKey(
        AgentExecution,
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=False,
    )
    sequence = models.PositiveBigIntegerField()
    execution_sequence = models.PositiveIntegerField()
    role = models.CharField(max_length=32)
    provenance = models.CharField(max_length=16, choices=Provenance.choices)
    content = models.JSONField(default=list)
    provider_stop_reason = models.CharField(max_length=64, blank=True)
    input_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    output_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cache_read_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cache_write_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    latency_ms = models.PositiveBigIntegerField(null=True, blank=True)
    is_truncated = models.BooleanField(default=False)
    original_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)

    def _validate_execution_conversation(self) -> None:
        if self.execution_id is None or self.conversation_id is None:
            return
        execution = self._state.fields_cache.get("execution")
        execution_conversation_id = (
            execution.conversation_id
            if execution is not None
            else AgentExecution.objects.values_list("conversation_id", flat=True).get(
                id=self.execution_id
            )
        )
        if self.conversation_id != execution_conversation_id:
            raise ValidationError(
                {
                    "conversation": (
                        "Must match the conversation associated with execution."
                    )
                }
            )

    def clean(self) -> None:
        super().clean()
        self._validate_execution_conversation()

    def save(self, *args, **kwargs):
        self._validate_execution_conversation()
        return super().save(*args, **kwargs)

    class Meta:
        db_table = "research_ai_agent_execution_message"
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"], name="ra_agent_trace_sequence"
            ),
            models.UniqueConstraint(
                fields=["execution", "execution_sequence"],
                name="ra_agent_exec_msg_sequence",
            ),
        ]
