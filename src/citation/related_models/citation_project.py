from django.db import models
from jsonschema import validate
from django.core.validators import FileExtensionValidator

from citation.constants import CITATION_TYPE_CHOICES
from user.models import Organization
from utils.models import DefaultAuthenticatedModel


class CitationProject(DefaultAuthenticatedModel):
    project_name = models.CharField(
        max_length=1024,
    )
    organization = models.ForeignKey(
        Organization,
        related_name="citation_projects",
        on_delete=models.CASCADE,
    )
    # TODO: calvinhlee - add invitations feature
