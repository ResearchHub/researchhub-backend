from django.db import models
from utils.models import DefaultModel
from peer_review.models import PeerReviewRequest
from invite.models import Invitation


class PeerReviewInvite(Invitation):
    INVITED = 'INVITED'
    ACCEPTED = 'ACCEPTED'
    DECLINED = 'DECLINED'

    REQUEST_STATUS_CHOICES = [
        (INVITED, INVITED),
        (ACCEPTED, ACCEPTED),
        (DECLINED, DECLINED)
    ]

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
