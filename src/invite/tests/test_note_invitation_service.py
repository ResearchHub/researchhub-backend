import contextlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase

from invite.models import NoteInvitation
from invite.services import (
    NoteInvitationExpiredError,
    NoteInvitationRecipientMismatchError,
    NoteInvitationService,
)
from note.tests.helpers import create_note
from researchhub_access_group.constants import EDITOR, VIEWER
from user.constants.gatekeeper_constants import ELN
from user.models import Gatekeeper


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

    def test_accept_invite_claims_recipientless_invite_with_different_emails(self):
        # Arrange
        invite = self._create_note_invitation(
            recipient=None,
            recipient_email="invited@researchhub.com",
            invite_type=EDITOR,
        )
        other_user = self._create_user("other")

        # Act
        accepted_invite = self.service.accept_invite(invite.key, other_user)

        # Assert
        self.assertEqual(accepted_invite.id, invite.id)

        invite.refresh_from_db()
        self.assertTrue(invite.accepted)
        self.assertEqual(invite.recipient, other_user)

        permission = self.note.unified_document.permissions.get(user=other_user)
        self.assertEqual(permission.access_type, EDITOR)

        gatekeeper = Gatekeeper.objects.get(user=other_user, type=ELN)
        self.assertEqual(gatekeeper.email, invite.recipient_email)

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


class NoteInvitationServiceConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.sender = self._create_user("sender")
        self.first_recipient = self._create_user("first")
        self.second_recipient = self._create_user("second")
        self.note, _ = create_note(self.sender, None, title="Test note")

    def _create_user(self, username):
        email = f"{username}@researchhub.com"
        return get_user_model().objects.create_user(
            username=email,
            password=uuid.uuid4().hex,
            email=email,
        )

    def _accept_invite(self, key, user_id):
        close_old_connections()
        try:
            user = get_user_model().objects.get(id=user_id)
            NoteInvitationService().accept_invite(key, user)
            return "accepted"
        except NoteInvitationExpiredError:
            return "expired"
        finally:
            close_old_connections()

    def test_only_one_user_can_claim_recipientless_invite(self):
        # Arrange
        invite = NoteInvitation.create(
            expiration_time=1440,
            recipient=None,
            recipient_email="invited@researchhub.com",
            inviter_id=self.sender.id,
            note_id=self.note.id,
            invite_type=EDITOR,
        )
        claim_barrier = Barrier(2)
        original_claim = NoteInvitationService._claim_recipientless_invite

        def synchronized_claim(service, locked_invite, user):
            with contextlib.suppress(BrokenBarrierError):
                claim_barrier.wait(timeout=1)
            original_claim(service, locked_invite, user)

        # Act
        with (
            patch.object(
                NoteInvitationService,
                "_claim_recipientless_invite",
                synchronized_claim,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(
                executor.map(
                    lambda user_id: self._accept_invite(invite.key, user_id),
                    [self.first_recipient.id, self.second_recipient.id],
                )
            )

        # Assert
        self.assertCountEqual(results, ["accepted", "expired"])

        invite.refresh_from_db()
        self.assertTrue(invite.accepted)
        self.assertIn(
            invite.recipient_id,
            [self.first_recipient.id, self.second_recipient.id],
        )
        self.assertEqual(self.note.unified_document.permissions.count(), 1)
