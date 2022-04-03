from django.db import models

class PeerReviewRequest(models.Model):
    REQUESTED = 'REQUESTED'
    ACCEPTED = 'ACCEPTED'
    DECLINED = 'DECLINED'

    REQUEST_STATUS_CHOICES = [
        (REQUESTED, REQUESTED),
        (ACCEPTED, ACCEPTED),
        (DECLINED, DECLINED)
    ]

    invited_user = models.ForeignKey(
        'user.User',
        related_name='peer_review_requests',
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    invited_by_user = models.ForeignKey(
        'user.User',
        related_name='peer_reviews_requested',
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    status = models.CharField(
        choices=REQUEST_STATUS_CHOICES,
        max_length=32,
        default=REQUESTED,
        blank=False,
        null=False,
    )
