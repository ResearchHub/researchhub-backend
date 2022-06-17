from django.db import models

from hub.models import Hub
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.models import DefaultModel


class FeaturedContent(DefaultModel):
    hub = models.ForeignKey(
        Hub,
        default=None,
        blank=True,
        null=True,
        on_delete=models.CASCADE,
        related_name="featured_content",
    )

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        default=False,
        blank=False,
        null=False,
        on_delete=models.CASCADE,
        related_name="featured_in_hubs",
    )
