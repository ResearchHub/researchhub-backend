from django.db import models
from discussion.models import Thread
from researchhub_document.models import ResearchhubUnifiedDocument
from utils.models import DefaultModel


class PeerReview(DefaultModel):
    assigned_user = models.ForeignKey(
        'user.User',
        related_name='assigned_reviews',
        blank=False,
        null=False,
        on_delete=models.PROTECT,
    )

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        related_name='peer_reviews',
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )


class PeerReviewDecision(DefaultModel):
    APPROVED = 'APPROVED'
    CHANGES_REQUESTED = 'CHANGES_REQUESTED'

    DECISION_CHOICES = [
        (APPROVED, APPROVED),
        (CHANGES_REQUESTED, CHANGES_REQUESTED)
    ]

    peer_review = models.ForeignKey(
        PeerReview,
        blank=False,
        null=False,
        related_name='decisions',
        on_delete=models.CASCADE,
    )

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    doc_version = models.ForeignKey(
        'note.NoteContent',
        blank=True,
        null=True,
        related_name='peer_review_decisions',
        on_delete=models.SET_NULL,
    )

    decision = models.CharField(
        choices=DECISION_CHOICES,
        max_length=32,
        blank=False,
        null=False,
    )

    discussion_thread = models.OneToOneField(
        Thread,
        blank=True,
        null=True,
        related_name='peer_review_decision',
        on_delete=models.SET_NULL,
    )
