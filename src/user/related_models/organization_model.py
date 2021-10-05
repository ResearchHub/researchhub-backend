from django.db import models

from researchhub_access_group.models import ResearchhubAccessGroup
from utils.models import DefaultModel


class Organization(DefaultModel):
    access_group = models.ForeignKey(
        ResearchhubAccessGroup,
        related_name='organizations',
        on_delete=models.CASCADE,
    )
    cover_image = models.FileField(
        max_length=512,
        upload_to='organizations/cover_image/%Y/%m/%d',
        default=None,
        null=True,
        blank=True
    )
    description = models.CharField(default='', max_length=256)
    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(default='', max_length=1024, unique=True)
