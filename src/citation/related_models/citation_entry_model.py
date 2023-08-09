from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import FileExtensionValidator
from django.db import models

from citation.constants import CITATION_TYPE_CHOICES
from citation.related_models.citation_project_model import CitationProject
from researchhub_comment.models import RhCommentThreadModel
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import Organization
from utils.models import DefaultAuthenticatedModel


class CitationEntry(DefaultAuthenticatedModel):

    """--- MODEL FIELDS ---"""

    attachment = models.FileField(
        blank=True,
        default=None,
        max_length=1024,
        null=True,
        upload_to="uploads/citation_entry/attachment/%Y/%m/%d",
        validators=[FileExtensionValidator(["pdf"])],
    )
    citation_type = models.CharField(max_length=32, choices=CITATION_TYPE_CHOICES)
    checksum = models.CharField(max_length=16)
    doi = models.CharField(max_length=255, default=None, null=True, blank=True)
    fields = models.JSONField()
    organization = models.ForeignKey(
        Organization, related_name="created_citations", on_delete=models.CASCADE
    )
    project = models.ForeignKey(
        CitationProject,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="citations",
        related_query_name="citations",
    )
    related_unified_doc = models.ForeignKey(
        ResearchhubUnifiedDocument,
        null=True,
        on_delete=models.CASCADE,
        related_name="citation_entries",
    )
    rh_threads = GenericRelation(
        RhCommentThreadModel,
        related_query_name="citation",
    )

    """--- PROPERTIES ---"""

    @property
    def created_by_indexing(self):
        # For Elasticsearch indexing
        created_by = self.created_by
        first_name = created_by.first_name
        last_name = created_by.last_name
        return {
            "id": self.created_by.id,
            "first_name": first_name,
            "last_name": first_name,
            "full_name": f"{first_name} {last_name}",
        }

    @property
    def organization_indexing(self):
        # For Elasticsearch indexing
        return {"id": self.organization.id, "name": self.organization.name}

    """--- METHODS ---"""

    def is_user_allowed_to_edit(self, user):
        belonging_project = self.project
        if belonging_project is None:
            org_permissions = self.organization.permissions
            return org_permissions.has_editor_user(
                user
            ) or org_permissions.has_admin_user(user)
        else:
            project_permissions = belonging_project.permissions
            return project_permissions.has_editor_user(
                user
            ) or project_permissions.has_admin_user(user)
