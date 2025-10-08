from django.db import models
from django.db.models.functions import Lower

from user_lists.managers import ListManager
from utils.models import DefaultAuthenticatedModel, SoftDeletableModel


class ListItemDocumentContentType(models.TextChoices):
    PAPER = "paper", "Paper"
    GRANT = "grant", "Request for Proposal"
    PREREGISTRATION = "preregistration", "Proposal"

    @classmethod
    def max_len(cls):
        return max(len(v) for v in cls.values)


class ListItem(DefaultAuthenticatedModel, SoftDeletableModel):
    """
    An item referencing content (such as a paper, RFP, or proposal) saved to one of a user's List objects.
    """

    is_public = models.BooleanField(default=False)  # Override

    parent_list = models.ForeignKey(
        "List",
        on_delete=models.CASCADE,
        related_name="items",
        db_comment="The list that the item is saved to.",
    )

    document_content_type = models.CharField(
        max_length=ListItemDocumentContentType.max_len(),
        choices=ListItemDocumentContentType.choices,
        db_comment="The type of content the item represents.",
    )

    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        on_delete=models.CASCADE,
        related_name="user_list_items",
        db_comment="The saved document that the item represents.",
    )

    class Meta:
        ordering = ["-created_date"]

        constraints = [
            models.UniqueConstraint(
                fields=["parent_list", "unified_document", "document_content_type"],
                name="unique_not_removed_document_per_list",
                condition=models.Q(is_removed=False),
            ),
            models.CheckConstraint(
                check=models.Q(document_content_type=Lower("document_content_type")),
                name="document_content_type_lowercase",
            ),
        ]


class List(DefaultAuthenticatedModel, SoftDeletableModel):
    """
    A user's list consisting of `ListItem` objects the user has saved.
    """

    # Override default manager with an extended version that has custom queries
    objects = ListManager()

    name = models.CharField(max_length=120)
    is_public = models.BooleanField(default=False)  # Override

    class Meta:
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "name"],
                name="unique_not_removed_name_per_user",
                condition=models.Q(is_removed=False),
            )
        ]
