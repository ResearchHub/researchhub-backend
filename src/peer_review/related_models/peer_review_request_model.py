from django.db import models
from researchhub_document.models import ResearchhubUnifiedDocument
from utils.models import DefaultModel

class PeerReviewRequest(DefaultModel):
    PENDING = 'PENDING'
    CLOSED = 'CLOSED'

    REQUEST_STATUS_CHOICES = [
        (PENDING, PENDING),
        (CLOSED, CLOSED),
    ]

    requested_by_user = models.ForeignKey(
        'user.User',
        related_name='peer_review_requests',
        blank=False,
        null=True,
        on_delete=models.CASCADE,
    )

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        blank=False,
        null=True,
        related_name='peer_review_requests',
        on_delete=models.CASCADE,
    )

    doc_version = models.ForeignKey(
        'note.NoteContent',
        blank=False,
        null=True,
        on_delete=models.SET_NULL,
    )

    status = models.CharField(
        choices=REQUEST_STATUS_CHOICES,
        max_length=32,
        default=PENDING,
        blank=False,
        null=False,
    )

    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_date']