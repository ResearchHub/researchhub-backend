from django.db import models

from utils.models import DefaultModel


class ProposalDraft(DefaultModel):
    """
    Tracks a headless proposal-drafting job.

    One FK (``search_expert``) resolves both the Expert and, via
    ``expert_search.unified_document``, the Grant and GRANT post.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"
        # Stopped on request rather than by anything going wrong. Distinct from
        # FAILED so the record does not blame the run for a decision someone
        # made about it, and terminal like the rest -- which also releases
        # ``ra_pd_one_active_per_search_expert`` for a fresh attempt.
        CANCELLED = "CANCELLED"

    class Step(models.TextChoices):
        QUEUED = "QUEUED"
        BUILDING_PROFILE = "BUILDING_PROFILE"
        DRAFTING = "DRAFTING"
        JUDGING = "JUDGING"
        REVISING = "REVISING"
        VERIFYING = "VERIFYING"
        WRITING_NOTE = "WRITING_NOTE"
        DONE = "DONE"

    search_expert = models.ForeignKey(
        "research_ai.SearchExpert",
        on_delete=models.CASCADE,
        related_name="proposal_drafts",
    )
    agent_conversation = models.OneToOneField(
        "research_ai.AgentConversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposal_draft",
        db_comment=(
            "Durable agent history for this draft. SET_NULL keeps the completed "
            "proposal when trace data is deleted."
        ),
    )
    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_research_ai_proposal_drafts",
        db_comment=(
            "User who triggered the draft; null for system/automatic runs or if the "
            "user is later deleted (the job record is kept for diagnostics)."
        ),
    )
    note = models.ForeignKey(
        "note.Note",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="proposal_drafts",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    model_ref = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_comment=(
            "User-selected generator model as a provider-prefixed model ref; "
            "empty runs the configured default. What actually ran is "
            "snapshotted in run_config."
        ),
    )
    step = models.CharField(
        max_length=32,
        choices=Step.choices,
        default=Step.QUEUED,
        db_index=True,
    )
    rounds_used = models.IntegerField(default=0)
    run_config = models.JSONField(
        default=dict,
        blank=True,
        db_comment=(
            "Snapshot of the models/config that actually ran: generator model, judge "
            "panel roster, max_rounds, etc. Recorded for reproducibility since the "
            "engine's roster is configurable and the loop is non-deterministic."
        ),
    )
    final_scores = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Last panel rollup.",
    )
    gate_report = models.JSONField(
        default=dict,
        blank=True,
        db_comment="Programmatic gate results.",
    )
    last_submission = models.JSONField(
        default=dict,
        blank=True,
        db_comment=(
            "The last draft the agent submitted (sections, prosemirror, "
            "plain_text, citations). On a COMPLETED run the accepted draft also "
            "lives on the linked Note; this field exists so a FAILED run's "
            "rejected draft is still inspectable, since it is never written as a "
            "Note."
        ),
    )
    error_message = models.TextField(blank=True)
    processing_time = models.FloatField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    usage_reservation_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment=(
            "Renewable lease reserving the creator's Research AI budget slot while "
            "this draft may still be producing spend."
        ),
    )

    class Meta:
        db_table = "research_ai_proposal_draft"
        ordering = ["-created_date"]
        indexes = [
            models.Index(fields=["status"], name="research_ai_pd_status"),
            models.Index(
                fields=["search_expert", "status"],
                name="research_ai_pd_search_status",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["search_expert"],
                condition=models.Q(status__in=["PENDING", "PROCESSING"]),
                name="ra_pd_one_active_per_search_expert",
            ),
        ]

    def __str__(self):
        return f"ProposalDraft {self.id} ({self.status}/{self.step})"
