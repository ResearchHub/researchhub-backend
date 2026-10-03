from django.db import models

from invite.models import Invitation
from note.models import Note
from researchhub_access_group.constants import ACCESS_TYPE_CHOICES, VIEWER


class NoteInvitation(Invitation):
    invite_type = models.CharField(
        max_length=16, choices=ACCESS_TYPE_CHOICES, default=VIEWER
    )
    note = models.ForeignKey(
        Note, on_delete=models.CASCADE, related_name="invited_users"
    )
