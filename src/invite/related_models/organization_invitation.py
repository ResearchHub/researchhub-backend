from django.db import models

from invite.models import Invitation
from user.models import Organization
from utils.message import send_email_message


class OrganizationInvitation(Invitation):
    ADMIN = 'ADMIN'
    EDITOR = 'EDITOR'
    VIEWER = 'VIEWER'
    INVITE_TYPE_CHOICES = (
        (ADMIN, ADMIN),
        (EDITOR, EDITOR),
        (VIEWER, VIEWER)
    )

    invite_type = models.CharField(
        max_length=8,
        choices=INVITE_TYPE_CHOICES,
        default=VIEWER
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
    )

    def send_invitation(self):
        recipient = self.recipient
        organization = self.organization
        invite_type = self.invite_type.lower()
        template = 'organization_invite.txt'
        html_template = 'organization_invite.html'
        subject = 'ResearchHub | Organization Invitation'
        email_context = {
            'organization_title': organization.name,
            'access_type': invite_type.lower(),
            'user_name': f'{recipient.first_name} {recipient.last_name}'
        }
        send_email_message(
            [recipient.email],
            template,
            subject,
            email_context,
            html_template
        )
