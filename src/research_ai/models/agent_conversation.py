from django.db import models

from utils.models import DefaultModel


class AgentConversation(DefaultModel):
    """
    Durable container for one logical agent conversation.

    Owning records (e.g. ``ProposalDraft``) point at the conversation, not the
    other way around. A flow that changes the system prompt starts a new
    conversation.
    """

    class Kind(models.TextChoices):
        PROPOSAL_DRAFT = "PROPOSAL_DRAFT"
        NOTEBOOK_CHAT = "NOTEBOOK_CHAT"

    created_by = models.ForeignKey(
        "user.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_research_ai_agent_conversations",
        db_comment="Null for headless/system runs.",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    system_prompt = models.TextField(blank=True)

    class Meta:
        db_table = "research_ai_agent_conversation"
        ordering = ["-created_date"]

    def __str__(self):
        return f"AgentConversation {self.id} ({self.kind})"
