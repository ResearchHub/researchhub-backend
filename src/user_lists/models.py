from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultAuthenticatedModel, SoftDeletableModel


class List(DefaultAuthenticatedModel, SoftDeletableModel):
    name = models.CharField(max_length=120)

    def __str__(self):
        return f"{self.created_by}:{self.name}"
    class Meta:
        ordering = ["name"]
        indexes = [ 
            models.Index(
                fields=["created_by", "is_removed"],
                name="idx_list_user_removed",
            ),
        ]


class ListItem(DefaultAuthenticatedModel, SoftDeletableModel):
    parent_list = models.ForeignKey(
        List,
        on_delete=models.CASCADE,
        related_name="items",
    )

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        related_name="user_list_items",
    )

    class Meta:
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent_list", "unified_document"],
                condition=models.Q(is_removed=False),
                name="unique_document_per_list",
            )
        ]
        indexes = [
            models.Index(
                fields=["parent_list", "is_removed"],
                name="idx_listitem_list_removed",
            )
        ]

    def __str__(self):
        return str(self.id)

