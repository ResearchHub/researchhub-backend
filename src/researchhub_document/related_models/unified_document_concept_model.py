from django.db import models

from utils.models import DefaultModel


class UnifiedDocumentConcept(DefaultModel):
    concept = models.ForeignKey(
        "tag.Concept", related_name="concept", blank=True, on_delete=models.CASCADE
    )

    unified_document = models.ForeignKey(
        "researchhub_document.ResearchhubUnifiedDocument",
        related_name="concept",
        blank=True,
        on_delete=models.CASCADE,
    )

    relevancy_score = models.FloatField(
        default=0.0,
    )

    level = models.IntegerField(
        default=0,
    )

    @classmethod
    def create_or_update(cls, unified_document_id, concept_id, level, relevancy_score):
        concept, created = cls.objects.get_or_create(
            concept_id=concept_id,
            relevancy_score=relevancy_score,
            level=level,
            unified_document_id=unified_document_id,
        )

        if not created:
            concept.concept_id = concept_id
            concept.relevancy_score = relevancy_score
            concept.level = level
            concept.unified_document_id = unified_document_id
            concept.save()

        return concept
