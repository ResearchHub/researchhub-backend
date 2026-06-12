import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from invite.models import NoteInvitation
from invite.services import (
    NoteInvitationExpiredError,
    NoteInvitationRecipientMismatchError,
    NoteInvitationService,
)
from note.tests.helpers import create_note
from researchhub_access_group.constants import EDITOR, VIEWER


class NoteInvitationServiceTest(TestCase):
    def setUp(self):
        self.sender = self._create_user("sender")
        self.recipient = self._create_user("recipient")
        self.note, _ = create_note(self.sender, None, title="Test note")
        self.service = NoteInvitationService()

    def _create_user(self, username):
        email = f"{username}@researchhub.com"
        return get_user_model().objects.create_user(
            username=email,
            password=uuid.uuid4().hex,
            email=email,
        )

    def _create_note_invitation(
        self,
        recipient=None,
        recipient_email=None,
        expiration_time=1440,
        invite_type=VIEWER,
    ):
        if recipient_email is None:
            recipient = recipient or self.recipient
            recipient_email = recipient.email

        return NoteInvitation.create(
            expiration_time=expiration_time,
            recipient=recipient,
            recipient_email=recipient_email,
            inviter_id=self.sender.id,
            note_id=self.note.id,
            invite_type=invite_type,
        )

    def test_accept_invite_creates_permission_and_accepts_invite(self):
        # Arrange
        invite = self._create_note_invitation(invite_type=EDITOR)

        # Act
        accepted_invite = self.service.accept_invite(invite.key, self.recipient)

        # Assert
        self.assertEqual(accepted_invite.id, invite.id)

        invite.refresh_from_db()
        self.assertTrue(invite.accepted)

        permission = self.note.unified_document.permissions.get(user=self.recipient)
        self.assertEqual(permission.access_type, EDITOR)

    def test_accept_invite_claims_recipientless_invite(self):
        # Arrange
        invite = self._create_note_invitation(
            recipient=None,
            recipient_email="new-recipient@researchhub.com",
            invite_type=EDITOR,
        )
        new_recipient = self._create_user("new-recipient")

        # Act
        accepted_invite = self.service.accept_invite(invite.key, new_recipient)

        # Assert
        self.assertEqual(accepted_invite.id, invite.id)

        invite.refresh_from_db()
        self.assertTrue(invite.accepted)
        self.assertEqual(invite.recipient, new_recipient)

        permission = self.note.unified_document.permissions.get(user=new_recipient)
        self.assertEqual(permission.access_type, EDITOR)

    def test_accept_invite_rejects_recipientless_invite_with_different_emails(self):
        # Arrange
        invite = self._create_note_invitation(
            recipient=None,
            recipient_email="invited@researchhub.com",
        )
        other_user = self._create_user("other")

        # Act
        with self.assertRaises(NoteInvitationRecipientMismatchError):
            self.service.accept_invite(invite.key, other_user)

        # Assert
        invite.refresh_from_db()
        self.assertFalse(invite.accepted)
        self.assertIsNone(invite.recipient)
        self.assertFalse(
            self.note.unified_document.permissions.filter(user=other_user).exists()
        )

    def test_accept_invite_raises_for_expired_invite(self):
        # Arrange
        invite = self._create_note_invitation(expiration_time=-1)

        # Act
        with self.assertRaises(NoteInvitationExpiredError):
            self.service.accept_invite(invite.key, self.recipient)

        # Assert
        invite.refresh_from_db()
        self.assertFalse(invite.accepted)
        self.assertFalse(
            self.note.unified_document.permissions.filter(user=self.recipient).exists()
        )

    def test_accept_invite_raises_for_already_accepted_invite(self):
        # Arrange
        invite = self._create_note_invitation()
        invite.accept()

        # Act
        with self.assertRaises(NoteInvitationExpiredError):
            self.service.accept_invite(invite.key, self.recipient)

        # Assert
        self.assertFalse(
            self.note.unified_document.permissions.filter(user=self.recipient).exists()
        )

    def test_accept_invite_raises_for_recipient_mismatch(self):
        # Arrange
        invite = self._create_note_invitation()
        other_user = self._create_user("other")

        # Act
        with self.assertRaises(NoteInvitationRecipientMismatchError):
            self.service.accept_invite(invite.key, other_user)

        # Assert
        invite.refresh_from_db()
        self.assertFalse(invite.accepted)
        self.assertFalse(
            self.note.unified_document.permissions.filter(user=other_user).exists()
        )
