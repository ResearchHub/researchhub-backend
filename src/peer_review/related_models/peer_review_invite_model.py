from django.db import models
from utils.models import DefaultModel
from peer_review.models import PeerReviewRequest


class PeerReviewInvite(DefaultModel):
    INVITED = 'INVITED'
    ACCEPTED = 'ACCEPTED'
    DECLINED = 'DECLINED'

    REQUEST_STATUS_CHOICES = [
        (INVITED, INVITED),
        (ACCEPTED, ACCEPTED),
        (DECLINED, DECLINED)
    ]

    invited_user = models.ForeignKey(
        'user.User',
        related_name='peer_review_invites',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    invited_email = models.EmailField(
        unique=False,
        null=True,
        blank=True,
    )

    invited_by_user = models.ForeignKey(
        'user.User',
        related_name='peer_review_users_invited',
        blank=False,
        null=True,
        on_delete=models.CASCADE,
    )

    peer_review_request = models.ForeignKey(
        PeerReviewRequest,
        related_name='invites',
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    status = models.CharField(
        choices=REQUEST_STATUS_CHOICES,
        max_length=32,
        default=INVITED,
        blank=False,
        null=False,
    )
