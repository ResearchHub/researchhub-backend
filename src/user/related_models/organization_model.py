from django.db import models

from researchhub_access_group.models import ResearchhubAccessGroup
from utils.models import DefaultModel


class Organization(DefaultModel):
    access_group = models.OneToOneField(
        ResearchhubAccessGroup,
        related_name='organization',
        on_delete=models.CASCADE,
    )
    cover_image = models.FileField(
        max_length=512,
        upload_to='organizations/cover_image/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    description = models.CharField(max_length=256)
    name = models.CharField(max_length=64)
