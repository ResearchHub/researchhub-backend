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
        db_index=True,
    )

    total_citation_count = models.IntegerField()

    citation_change = models.IntegerField()

    source = models.CharField(
        max_length=255, choices=[(source.value, source.name) for source in Source]
    )

    @classmethod
    def citation_count(cls, paper):
        return (
            cls.objects.filter(paper=paper)
            .order_by("-created_date")
            .values_list("total_citation_count", flat=True)
            .first()
        ) or 0
