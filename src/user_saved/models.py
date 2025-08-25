from django.db import models
from django.db.models import Q
from django.utils.crypto import get_random_string

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.user_model import User
from utils.models import DefaultAuthenticatedModel, SoftDeletableModel


class UserSavedList(DefaultAuthenticatedModel, SoftDeletableModel):
    """
    Model for user-created lists of saved documents
    """

    list_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    is_public = models.BooleanField(default=False)
    share_token = models.CharField(max_length=50, unique=True, blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "list_name"],
                name="unique_user_list_name",
            ),
        ]
        indexes = [
            models.Index(fields=["share_token"], name="idx_share_token"),
        ]

    def __str__(self):
        return f"{self.list_name} (by {self.created_by.username})"

    def save(self, *args, **kwargs):
        # Generate share token for public lists if not already set
        if self.is_public and not self.share_token:
            self.share_token = get_random_string(32)
        super().save(*args, **kwargs)

    def get_share_url(self):
        """Get the share URL for this list"""
        if self.is_public and self.share_token:
            from django.conf import settings

            base_url = getattr(settings, "SITE_URL", "http://localhost:8000")
            return f"{base_url}/shared/list/{self.share_token}/"
        return None


class UserSavedEntry(DefaultAuthenticatedModel, SoftDeletableModel):
    """
    Model for individual documents saved in a list
    """

    parent_list = models.ForeignKey(
        UserSavedList,
        on_delete=models.CASCADE,
        related_name="usersavedentry_set",
    )
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    document_deleted = models.BooleanField(default=False)
    document_deleted_date = models.DateTimeField(null=True, blank=True)
    document_title_snapshot = models.CharField(max_length=500, blank=True, null=True)
    document_type_snapshot = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parent_list", "unified_document"],
                name="unique_list_document",
                condition=Q(unified_document__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=["document_deleted"], name="idx_document_deleted"),
        ]

    def __str__(self):
        if self.unified_document:
            return f"{self.unified_document} in {self.parent_list.list_name}"
        else:
            return f"Deleted document in {self.parent_list.list_name}"

    def save(self, *args, **kwargs):
        # Capture document snapshot if document exists
        if self.unified_document and not self.document_title_snapshot:
            self.document_title_snapshot = self._get_document_title()
            self.document_type_snapshot = self.unified_document.document_type
        super().save(*args, **kwargs)

    def _get_document_title(self):
        """Get document title safely"""
        try:
            if self.unified_document.document_type == "PAPER":
                return (
                    self.unified_document.paper.title
                    if hasattr(self.unified_document, "paper")
                    else None
                )
            elif self.unified_document.document_type == "DISCUSSION":
                post = self.unified_document.posts.first()
                return post.title if post else None
            else:
                return getattr(self.unified_document, "title", None)
        except Exception:
            return "Unknown Document"


class UserSavedListPermission(DefaultAuthenticatedModel):
    """
    Model for managing permissions on user saved lists
    """

    PERMISSION_CHOICES = [
        ("VIEW", "View"),
        ("EDIT", "Edit"),
        ("ADMIN", "Admin"),
    ]

    list = models.ForeignKey(
        UserSavedList, on_delete=models.CASCADE, related_name="permissions"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    permission = models.CharField(
        max_length=10, choices=PERMISSION_CHOICES, default="VIEW"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["list", "user"],
                name="unique_list_user_permission",
            ),
        ]
        indexes = [
            models.Index(
                fields=["list", "user", "permission"],
                name="idx_list_user_permission",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.permission} on {self.list.list_name}"
