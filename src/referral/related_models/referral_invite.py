from django.db import models
from django.db.models import Sum

from invite.models import Invitation
from researchhub.settings import REFERRAL_PROGRAM
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

    def _send_bounty_invitation(self):
        inviter = self.inviter
        email = self.recipient_email
        template = "referral_invite.txt"
        html_template = "referral_bounty_invite.html"
        inviter_name = f"{inviter.first_name} {inviter.last_name}"
        subject = f"{inviter_name} has invited you to complete a bounty on ResearchHub"
        uni_doc = self.unified_document
        url = uni_doc.frontend_view_link()
        uni_doc.bounties.all()
        bounty_amount = round(
            ResearchhubUnifiedDocument.objects.get(id=uni_doc.id)
            .bounties.all()
            .aggregate(Sum("amount"))["amount__sum"]
        )

        email_context = {
            "inviter_name": inviter_name,
            "referral_url": f"http://localhost:3000/referral/{inviter.referral_code}",
            "document_title": uni_doc.get_document().title,
            "bounty_amount": bounty_amount,
            "referral_bonus": REFERRAL_PROGRAM["INVITED_EARN_AMOUNT"],
            "document_url": url,
        }

        send_email_message([email], template, subject, email_context, html_template)

    def _send_referral_invitation(self):
        inviter = self.inviter
        email = self.recipient_email
        template = "referral_invite.txt"
        html_template = "referral_bounty_invite.html"
        inviter_name = f"{inviter.first_name} {inviter.last_name}"
        subject = f"{inviter_name} has invited you to complete a bounty on ResearchHub"

        email_context = {
            "inviter_name": inviter_name,
            "referral_url": "http://localhost:3000/referral/cf41a714-defd-48c8-87df-acb66a7c18c5",
            "document_title": "Some bounty title",
            "bounty_amount": 470,
            "referral_bonus": REFERRAL_PROGRAM["INVITED_EARN_AMOUNT"],
            "document_url": "https://stackoverflow.com/questions/24912173/django-1-7-makemigrations-not-detecting-changes",
        }

        send_email_message([email], template, subject, email_context, html_template)

    def send_invitation(self):
        invite_type = self.invite_type

        if invite_type == "BOUNTY":
            self._send_bounty_invitation()
        else:
            self._send_referral_invitation()
