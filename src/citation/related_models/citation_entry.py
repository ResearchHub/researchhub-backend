from django.db import models
from jsonschema import validate
from django.core.validators import FileExtensionValidator

from citation.constants import CITATION_TYPE_CHOICES
from citation.related_models.citation_project import CitationProject
from citation.schema import generate_schema_for_citation
from user.models import Organization
from utils.models import DefaultAuthenticatedModel


class CitationEntry(DefaultAuthenticatedModel):
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
    organization = models.ForeignKey(
        Organization, related_name="created_citations", on_delete=models.CASCADE
    )
    project = models.ForeignKey(
        CitationProject,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="citations",
    )
    fields = models.JSONField()
