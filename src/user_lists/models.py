from django.db import models
from django.utils import timezone

from researchhub_document.related_models.researchhub_unified_document_model import ResearchhubUnifiedDocument
from utils.models import DefaultAuthenticatedModel, SoftDeletableModel


class List(DefaultAuthenticatedModel, SoftDeletableModel):
    name = models.CharField(max_length=120)
    is_public = models.BooleanField(default=False)

    class Meta:
        ordering = ["-updated_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "name"],
                condition=models.Q(is_removed=False),
                name="unique_not_removed_name_per_user",
            )
        ]
        indexes = [
            models.Index(fields=["created_by", "is_removed"], name="idx_list_user_removed"),
        ]

    def __str__(self):
        return f"{self.created_by}:{self.name}"

    def update_timestamp(self, user):
        self.updated_date = timezone.now()
        self.updated_by = user
        self.save(update_fields=["updated_date", "updated_by"])

    @property
    def active_items(self):
        return self.items.filter(is_removed=False)

    def can_be_accessed_by(self, user):
        return not self.is_removed

    def can_be_modified_by(self, user):
        return self.created_by == user and not self.is_removed


class ListItem(DefaultAuthenticatedModel, SoftDeletableModel):
    parent_list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="items")
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument, on_delete=models.CASCADE, related_name="user_list_items"
    )
    is_public = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent_list", "unified_document"],
                condition=models.Q(is_removed=False),
                name="unique_not_removed_document_per_list",
            )
        ]
        indexes = [models.Index(fields=["parent_list", "is_removed"], name="idx_listitem_list_removed")]

    def __str__(self):
        return f"{self.created_by}:{self.parent_list}:{self.unified_document.get_client_doc_type()}:{self.unified_document.get_url()}"

    @classmethod
    def find_existing(cls, parent_list, unified_document):
        return cls.objects.filter(
            parent_list=parent_list, unified_document=unified_document, is_removed=False
        ).first()
