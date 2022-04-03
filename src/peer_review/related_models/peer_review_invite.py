from django.db import models


class PeerReviewInvite(models.Model):
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
        blank=False,
        null=False,
        on_delete=models.CASCADE,
    )

    invited_by_user = models.ForeignKey(
        'user.User',
        related_name='peer_review_users_invited',
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
