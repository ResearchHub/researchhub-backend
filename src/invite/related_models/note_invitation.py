from django.db import models

from invite.models import Invitation
from utils.message import send_email_message
from note.models import Note
from researchhub_access_group.constants import ACCESS_TYPE_CHOICES, VIEWER
from researchhub.settings import BASE_FRONTEND_URL


class NoteInvitation(Invitation):

    invite_type = models.CharField(
        max_length=8,
        choices=ACCESS_TYPE_CHOICES,
        default=VIEWER
    )
    note = models.ForeignKey(
        Note,
        on_delete=models.CASCADE,
        related_name='invited_users'
    )

    def send_invitation(self):
        key = self.key
        recipient = self.recipient
        email = self.recipient_email
        note = self.note
        invite_type = self.invite_type.lower()
        template = 'note_invite.txt'
        html_template = 'note_invite.html'
        subject = 'ResearchHub | Note Collaboration'
        email_context = {
            'access_type': invite_type.lower(),
            'note_title': note.title,
            'note_link': f'{BASE_FRONTEND_URL}/note/join/{key}',
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
