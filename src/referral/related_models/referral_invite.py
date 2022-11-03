from django.db import models

from invite.models import Invitation
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from utils.message import send_email_message

JOIN_RH = "JOIN_RH"
BOUNTY = "BOUNTY"

INVITE_TYPE_CHOICES = [(JOIN_RH, JOIN_RH), (BOUNTY, BOUNTY)]


class ReferralInvite(Invitation):
    invite_type = models.CharField(
        choices=INVITE_TYPE_CHOICES,
        max_length=32,
        default=JOIN_RH,
        blank=False,
        null=False,
    )

    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        null=True,
        on_delete=models.CASCADE,
        related_name="referral_invites",
    )

    def send_invitation(self):
        inviter = self.inviter
        email = self.recipient_email
        invite_type = self.invite_type
        template = (
            "referral_invite.txt" if invite_type == "BOUNTY" else "bounty_invite.txt"
        )
        html_template = "referral_invite.html"
        inviter_name = f"{inviter.first_name} {inviter.last_name}"
        subject = f"{inviter_name} has invited you to join ResearchHub"

        if invite_type == "BOUNTY":
            subject = (
                f"{inviter_name} has invited you to complete a bounty on ResearchHub"
            )

        email_context = {
            "invite_type": invite_type,
            "inviter_name": inviter_name,
            "document_url": "https://stackoverflow.com/questions/24912173/django-1-7-makemigrations-not-detecting-changes",
        }

        send_email_message([email], template, subject, email_context, html_template)
