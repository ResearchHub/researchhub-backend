from django.db import models

from paper.models import Paper
from researchhub_document.related_models.constants.document_type import (
  DOCUMENT_TYPES, PAPER
)
from utils.models import DefaultModel


class ResearchhubUnifiedDocument(DefaultModel):
    # TODO: calvinhlee add 1:1 field Access Control - mostly used for ELN
    is_public = models.BooleanField(
      blank=False,
      default=True,
      help_text="Public posts are visible in home feed",
      null=False,
    )
    document_type = models.CharField(
      choices=DOCUMENT_TYPES,
      default=PAPER,
      max_length=32,
      null=False,
      help_text="Papers are imported from external src. Posts are in-house"
    )
    hot_score = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Feed ranking score",
    )
    paper = models.OneToOneField(
        Paper,
        db_index=True,
        on_delete=models.CASCADE,
        related_name="unified_document"
    )
