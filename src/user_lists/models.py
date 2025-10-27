from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultAuthenticatedModel, SoftDeletableModel

IS_PUBLIC_EXPLAINER = "This list is publically viewable"


class List(DefaultAuthenticatedModel, SoftDeletableModel):
    name = models.CharField(max_length=120)
    # Override the is_public field to set default to False
    is_public = models.BooleanField(default=False, help_text=IS_PUBLIC_EXPLAINER)

    def __str__(self):
        return f"{self.created_by}:{self.name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "name"],
                condition=models.Q(is_removed=False),
                name="unique_not_removed_name_per_user",
            )
        ]
        indexes = [
            models.Index(
                fields=["created_by", "name", "is_removed"],
                name="idx_user_list_name_removed",
            ),
            models.Index(
                fields=["created_by", "is_removed"],
                name="idx_user_removed",
            ),
        ]
        ordering = ["name"]


class ListItem(DefaultAuthenticatedModel, SoftDeletableModel):
    """
    ListItem models a row for a user's saved content, which is a UnifiedDocument
    """

    list = models.ForeignKey(
        List,
        on_delete=models.CASCADE,
        related_name="items",
        db_comment="The list that the item is saved to.",
    )

    document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        related_name="user_list_items",
        db_comment="The saved document that the item represents.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["list", "document"],
                condition=models.Q(is_removed=False),
                name="unique_not_removed_document_per_list",
            )
        ]
        indexes = [
            models.Index(
                fields=["list", "is_removed"],
                name="idx_list_removed",
            )
        ]
        ordering = ["-created_date"]

    def __str__(self):
        return f"{self.created_by}:{self.list}: \
            {self.document.get_client_doc_type()}:\
                {self.document.get_url()}"
