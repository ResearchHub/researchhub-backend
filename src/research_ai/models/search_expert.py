from django.db import models

from research_ai.models.expert import Expert
from research_ai.models.expert_search import ExpertSearch
from utils.models import DefaultModel


class SearchExpert(DefaultModel):
    """
    Membership of an Expert in one ExpertSearch (at most once per search).
    """

    expert_search = models.ForeignKey(
        ExpertSearch,
        on_delete=models.CASCADE,
        related_name="search_experts",
    )
    expert = models.ForeignKey(
        Expert,
        on_delete=models.CASCADE,
        related_name="search_experts",
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "research_ai_search_expert"
        ordering = ["expert_search", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["expert_search", "expert"],
                name="research_ai_se_search_expert_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["expert_search", "position"],
                name="ra_se_search_pos_idx",
            ),
        ]

    def __str__(self):
        return f"SearchExpert search={self.expert_search_id} expert={self.expert_id}"
