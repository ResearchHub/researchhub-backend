from django.db import models

from hub.models import Hub
from paper.models import Paper
from researchhub_access_group.models import ResearchhubAccessGroup
from researchhub_document.related_models.constants.document_type import (
  DOCUMENT_TYPES, PAPER
)
from utils.models import DefaultModel


class ResearchhubUnifiedDocument(DefaultModel):
    access_group = models.OneToOneField(
        ResearchhubAccessGroup,
        blank=True,
        help_text='Mostly used for ELN',
        null=True,
        on_delete=models.SET_NULL,
        related_name='document'
    )
    document_type = models.CharField(
      choices=DOCUMENT_TYPES,
      default=PAPER,
      max_length=32,
      null=False,
      help_text='Papers are imported from external src. Posts are in-house'
    )
    hot_score = models.IntegerField(
        default=0,
        db_index=True,
        help_text='Feed ranking score',
    )
    hubs = models.ManyToManyField(
        Hub,
        related_name='related_documents',
        blank=True
    )
    paper = models.OneToOneField(
        Paper,
        db_index=True,
        on_delete=models.CASCADE,
        related_name='unified_document'
    )

    @property
    def is_public(self):
        if (self.access_group is None):
            return True
        else:
            return self.access_group.is_public
