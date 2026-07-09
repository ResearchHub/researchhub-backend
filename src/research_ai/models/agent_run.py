from django.db import models

from utils.models import DefaultModel

from .agent_conversation import AgentConversation


class AgentRun(DefaultModel):
    """
    One ``Agent.run()`` / ``continue_conversation()`` invocation.

    Aggregate usage is denormalized (summed as turns land) so run-level
    analytics -- cost per run, cache hit rate, iteration distributions,
    failure taxonomy -- are single-table queries.
    """

    class Status(models.TextChoices):
        RUNNING = "RUNNING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    conversation = models.ForeignKey(
        AgentConversation,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True,
    )
    stop_reason = models.CharField(
        max_length=32,
        blank=True,
        db_comment=(
            "The AgentResult stop reason on success, or the error's stop "
            "reason (when it carries one) on failure."
        ),
    )
    iterations = models.IntegerField(default=0, db_comment="Model turns taken.")
    model_id = models.CharField(
        max_length=2048,
        blank=True,
        db_comment="The provider model actually used.",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        db_comment=(
            "Snapshot of the run's knobs: max_iterations, max_tokens, "
            "temperature, toolset names. Recorded for reproducibility."
        ),
    )
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cache_read_tokens = models.BigIntegerField(default=0)
    cache_write_tokens = models.BigIntegerField(default=0)
    error_message = models.TextField(blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(
        null=True,
        blank=True,
        db_comment="finished_at - created_date (created_date is the start).",
    )

    class Meta:
        db_table = "research_ai_agent_run"
        ordering = ["-created_date"]

    def __str__(self):
        return f"AgentRun {self.id} ({self.status})"
