from django.db import models

from invite.models import Invitation
from researchhub.settings import (
    ASSETS_BASE_URL,
    BASE_FRONTEND_URL,
)
from researchhub_access_group.constants import ACCESS_TYPE_CHOICES, VIEWER
from user.models import Organization
from utils.message import send_email_message


class OrganizationInvitation(Invitation):

    invite_type = models.CharField(
        max_length=12, choices=ACCESS_TYPE_CHOICES, default=VIEWER
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invited_users"
    )

    def send_invitation(self):
        key = self.key
        inviter = self.inviter
        recipient = self.recipient
        email = self.recipient_email
        organization = self.organization
        invite_type = self.invite_type.lower()
        template = "organization_invite.txt"
        html_template = "organization_invite.html"
        inviter_name = f"{inviter.first_name} {inviter.last_name}"
        subject = f"{inviter_name} has invited you to join {organization.name}"
        email_context = {
            "access_type": invite_type.lower(),
            "assets_base_url": ASSETS_BASE_URL,
            "organization_title": organization.name,
            "organization_link": f"{BASE_FRONTEND_URL}/org/join/{key}",
            "inviter_name": inviter_name,
        }

        if recipient:
            email_context["user_name"] = f"{recipient.first_name} {recipient.last_name}"
        else:
            email_context["user_name"] = "User"

        send_email_message([email], template, subject, email_context, html_template)
