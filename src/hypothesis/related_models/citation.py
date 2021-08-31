from django.db import models

from discussion.reaction_models import AbstractGenericReactionModel
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
    hypothesis = models.ForeignKey(
        Hypothesis,
        db_index=True,
        null=False,
        on_delete=models.CASCADE,
        related_name='citations'
    )
    source = models.OneToOneField(
        ResearchhubUnifiedDocument,
        related_name='citation',
        null=False,
        on_delete=models.CASCADE
    )

    def get_promoted_score(self):
        # TODO: leo | thomasvu - add logic / instance method
        return 0
