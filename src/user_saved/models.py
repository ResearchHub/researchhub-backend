from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultAuthenticatedModel, SoftDeletableModel

IS_PUBLIC_EXPLAINER = "This list is publically viewable"


class UserSavedList(DefaultAuthenticatedModel, SoftDeletableModel):
    list_name = models.CharField(max_length=200, null=False)
    # For now, override the is_public field to set default to False
    is_public = models.BooleanField(default=False, help_text=IS_PUBLIC_EXPLAINER)

    def __str__(self):
        return f"{self.created_by}:{self.list_name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "list_name"],
                condition=models.Q(is_removed=False),
                name="unique_user_list_name_not_removed",
            )
        ]
        indexes = [
            models.Index(
                fields=["created_by", "list_name", "is_removed"],
                name="idx_user_list_removed",
            ),
            models.Index(
                fields=["created_by", "is_removed"],
                name="idx_user_removed",
            ),
        ]


# This models a row for a user's saved content, which is a UnifiedDocument
class UserSavedEntry(DefaultAuthenticatedModel, SoftDeletableModel):

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        db_comment="The unified document associated with the saved content entry.",
    )

    parent_list = models.ForeignKey(
        UserSavedList,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parent_list", "unified_document"],
                condition=models.Q(is_removed=False),
                name="unique_active_list_and_doc",
            )
        ]
        indexes = [
            models.Index(
                fields=["parent_list", "is_removed"],
                name="idx_list_removed",
            )
        ]

    def __str__(self):
        return f"{self.created_by}:{self.parent_list}: \
            {self.unified_document.get_client_doc_type()}:\
                {self.unified_document.get_url()}"
