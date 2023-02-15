from django.db import models

from user.models import Organization, User

from ..constants import CITATION_TYPE_CHOICES


class CitationEntry(models.Model):
    created_by = models.ForeignKey(
        User, related_name="created_citations", on_delete=models.CASCADE
    )

    citation_type = models.CharField(max_length=32, choices=CITATION_TYPE_CHOICES)
    checksum = models.CharField(max_length=16)
    organization = models.ForeignKey(
        Organization, related_name="created_citations", on_delete=models.CASCADE
    )
    fields = models.JSONField()
