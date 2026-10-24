from django.db import models

from research_ai.models.agent import AgentConversationMessage
from utils.models import DefaultModel


class AgentMessageScreening(DefaultModel):
    """A decision model's verdict on whether a chat message is spam or off-purpose.

    A flagged message's turn fails before the model sees it. Probabilities
    are null when the call failed, and ``error`` says why; such a message is
    let through.
    """

    message = models.OneToOneField(
        AgentConversationMessage,
        on_delete=models.CASCADE,
        related_name="screening",
    )
    model = models.CharField(max_length=255, blank=True)
    promotional = models.FloatField(null=True, blank=True)
    off_purpose = models.FloatField(null=True, blank=True)
    flagged = models.BooleanField(default=False)
    cost_microusd = models.PositiveBigIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        db_table = "research_ai_agent_message_screening"
        indexes = [
            models.Index(
                fields=["flagged", "created_date"], name="ra_screening_flagged_date"
            ),
        ]
