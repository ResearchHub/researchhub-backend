from django.db import models

from utils.models import DefaultModel


class LLMUsageEvent(DefaultModel):
    """Immutable accounting row for one provider model call."""

    user = models.ForeignKey(
        "user.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="research_ai_usage_events",
    )
    feature = models.CharField(max_length=64, db_index=True)
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=255)
    input_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    output_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cache_read_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cache_write_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    cost_microusd = models.PositiveBigIntegerField(null=True, blank=True)
    execution = models.ForeignKey(
        "research_ai.AgentExecution",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="usage_events",
    )

    class Meta:
        db_table = "research_ai_llm_usage_event"
        indexes = [
            models.Index(fields=["user", "created_date"], name="ra_usage_user_date"),
        ]
