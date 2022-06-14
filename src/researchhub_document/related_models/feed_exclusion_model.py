from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultModel


class FeedExclusion(DefaultModel):
    # Not a foreign key because hub_id=0 is homepage
    hub_id = models.IntegerField(
        null=False,
        blank=False,
        db_index=True,
    )

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        default=False,
        blank=False,
        null=False,
        on_delete=models.CASCADE,
        related_name="excluded_from_feeds",
    )
