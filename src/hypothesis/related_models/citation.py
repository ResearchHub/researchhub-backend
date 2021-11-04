from django.db import models

from discussion.reaction_models import AbstractGenericReactionModel
from hypothesis.constants.constants import CITATION_TYPE, CITATION_TYPE_CHOICES
from researchhub_document.models import ResearchhubUnifiedDocument
from hypothesis.models import Hypothesis
from user.models import User


class Citation(AbstractGenericReactionModel):
    created_by = models.ForeignKey(
        User,
        db_index=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='created_citations',
    )
    hypothesis = models.ManyToManyField(
        Hypothesis,
        db_index=True,
        related_name='citations'
    )
    source = models.ForeignKey(
        ResearchhubUnifiedDocument,
        related_name='citation',
        null=False,
        on_delete=models.CASCADE
    )
    type = models.CharField(
        blank=False,
        choices=CITATION_TYPE_CHOICES,
        db_index=True,
        default=CITATION_TYPE['SUPPORT'],
        max_length=255,
    )

    def get_promoted_score(self):
        # TODO: leo | thomasvu - add logic / instance method
        return 0
