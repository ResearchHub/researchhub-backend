from enum import Enum

from django.db import models

from utils.models import DefaultModel


class Source(Enum):
    OpenAlex = "OpenAlex"
    Legacy = "Legacy"


class Citation(DefaultModel):
    paper = models.ForeignKey(
        "paper.paper",
        on_delete=models.CASCADE,
        related_name="paper_citations",
    )

    total_citation_count = models.IntegerField()

    citation_change = models.IntegerField()

    source = models.CharField(
        max_length=255, choices=[(source.value, source.name) for source in Source]
    )
