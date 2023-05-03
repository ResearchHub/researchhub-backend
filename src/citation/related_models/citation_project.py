from django.db import models
from jsonschema import validate

from user.models import Organization
from utils.models import DefaultAuthenticatedModel


class CitationProject(DefaultAuthenticatedModel):
    parent = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    project_name = models.CharField(
        max_length=1024,
    )
    organization = models.ForeignKey(
        Organization,
        related_name="citation_projects",
        on_delete=models.CASCADE,
    )
    # TODO: calvinhlee - add invitations feature
