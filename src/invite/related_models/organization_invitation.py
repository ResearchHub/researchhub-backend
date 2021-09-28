from django.db import models

from invite.models import Invitation
from user.models import Organization
from utils.message import send_email_message
from researchhub.settings import BASE_FRONTEND_URL


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
        key = self.key
        recipient = self.recipient
        organization = self.organization
        invite_type = self.invite_type.lower()
        template = 'organization_invite.txt'
        html_template = 'organization_invite.html'
        subject = 'ResearchHub | Organization Invitation'
        email_context = {
            'access_type': invite_type.lower(),
            'organization_title': organization.name,
            'organization_link': f'{BASE_FRONTEND_URL}/placeholder/{key}/join',
            'user_name': f'{recipient.first_name} {recipient.last_name}'
        }
        send_email_message(
            [recipient.email],
            template,
            subject,
            email_context,
            html_template
        )
