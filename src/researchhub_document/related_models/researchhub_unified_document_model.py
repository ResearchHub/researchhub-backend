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
        help_text='Feed ranking score.',
    )
    hubs = models.ManyToManyField(
        Hub,
        related_name='related_documents',
        blank=True
    )
    paper = models.OneToOneField(
        Paper,
        db_index=True,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_document',
    )
    score = models.IntegerField(
        default=0,
        db_index=True,
        help_text='Another feed ranking score.',
    )
    is_removed = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Unified Document is removed (deleted)'
    )

    @property
    def is_public(self):
        if (self.access_group is None):
            return True
        else:
            return self.access_group.is_public

    @property
    def created_by(self):
        if (self.document_type == PAPER):
            return self.paper.created_by
        else:
            first_post = self.posts.first()
            if (first_post is not None):
                return first_post.created_by
            return None
