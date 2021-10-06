from django.db import models

from invite.models import Invitation
from user.models import Organization
from utils.message import send_email_message
from researchhub_access_group.constants import ACCESS_TYPE_CHOICES, VIEWER
from researchhub.settings import BASE_FRONTEND_URL


class OrganizationInvitation(Invitation):

    invite_type = models.CharField(
        max_length=8,
        choices=ACCESS_TYPE_CHOICES,
        default=VIEWER
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='invited_users'
    )

    def send_invitation(self):
        key = self.key
        recipient = self.recipient
        email = self.recipient_email
        organization = self.organization
        invite_type = self.invite_type.lower()
        template = 'organization_invite.txt'
        html_template = 'organization_invite.html'
        subject = 'ResearchHub | Organization Invitation'
        email_context = {
            'access_type': invite_type.lower(),
            'organization_title': organization.name,
            'organization_link': f'{BASE_FRONTEND_URL}/org/join/{key}',
        }

        if recipient:
            email_context['user_name'] = f'{recipient.first_name} {recipient.last_name}'
        else:
            email_context['user_name'] = 'User'

        send_email_message(
            [email],
            template,
            subject,
            email_context,
            html_template
        )
