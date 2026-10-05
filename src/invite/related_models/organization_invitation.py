from django.db import models
from django.utils.html import format_html

from invite.models import Invitation
from mailing_list.services import EmailService
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_access_group.constants import ACCESS_TYPE_CHOICES, VIEWER
from user.models import Organization


class OrganizationInvitation(Invitation):
    invite_type = models.CharField(
        max_length=16, choices=ACCESS_TYPE_CHOICES, default=VIEWER
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invited_users"
    )

    def send_invitation(self):
        inviter = self.inviter
        recipient = self.recipient
        organization_name = self.organization.name
        inviter_name = f"{inviter.first_name} {inviter.last_name}"
        user_name = (
            f"{recipient.first_name} {recipient.last_name}" if recipient else "User"
        )
        subject = f"{inviter_name} has invited you to join {organization_name}"
        email_context = {
            "subject": f"{organization_name} Invitation",
            "body": format_html(
                "<p>Hey there {},</p>"
                "<p>{} has invited you to join their organization <b>{}</b>. "
                "Click below to accept their invitation!</p>",
                user_name,
                inviter_name,
                organization_name,
            ),
            "cta_url": f"{BASE_FRONTEND_URL}/org/join/{self.key}",
            "cta_label": f"Go to {organization_name}",
        }

        EmailService().send_email(
            [self.recipient_email],
            subject,
            email_context,
            template="general_branded_email",
        )
