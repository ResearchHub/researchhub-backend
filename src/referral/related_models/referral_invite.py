from django.db import models
from django.db.models import Sum

from invite.models import Invitation
from reputation.related_models.bounty import Bounty
from researchhub.settings import BASE_FRONTEND_URL, REFERRAL_PROGRAM
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

    referral_first_name = models.CharField(max_length=256, blank=True, null=True)

    referral_last_name = models.CharField(max_length=256, blank=True, null=True)

    def _send_bounty_invitation(self):
        inviter = self.inviter
        email = self.recipient_email
        template = "referral_invite.txt"
        html_template = "referral_bounty_invite.html"
        inviter_name = f"{inviter.first_name} {inviter.last_name}"
        subject = f"{inviter_name} has invited you to complete a bounty on ResearchHub"
        uni_doc = self.unified_document
        url = uni_doc.frontend_view_link()
        bounty_amount = round(
            uni_doc.related_bounties.filter(status=Bounty.OPEN).aggregate(
                Sum("amount")
            )["amount__sum"]
        )
        referral_name = f"{self.referral_first_name}"

        email_context = {
            "referral_name": referral_name,
            "inviter_name": inviter_name,
            "referral_url": f"{BASE_FRONTEND_URL}/referral/{inviter.referral_code}",
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
        html_template = "referral_join_invite.html"
        inviter_name = f"{inviter.first_name} {inviter.last_name}"
        subject = f"{inviter_name} has invited you to join ResearchHub"

        email_context = {
            "inviter_name": inviter_name,
            "referral_url": f"{BASE_FRONTEND_URL}/referral/{inviter.referral_code}",
            "referral_bonus": REFERRAL_PROGRAM["INVITED_EARN_AMOUNT"],
        }

        send_email_message([email], template, subject, email_context, html_template)

    def send_invitation(self):
        invite_type = self.invite_type

        if invite_type == "BOUNTY":
            self._send_bounty_invitation()
        else:
            self._send_referral_invitation()
