import uuid

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from invite.models import NoteInvitation
from note.tests.helpers import create_note


class PublicNoteInvitationViewsTest(APITestCase):
    """
    Tests public note access through invitation links.
    """

    def setUp(self):
        self.sender = get_user_model().objects.create_user(
            username="sender@researchhub.com",
            password=uuid.uuid4().hex,
            email="sender@researchhub.com",
        )
        self.recipient = get_user_model().objects.create_user(
            username="recipient@researchhub.com",
            password=uuid.uuid4().hex,
            email="recipient@researchhub.com",
        )
        self.note, _ = create_note(
            self.sender,
            None,
            title="Shared note",
            body="Readable note body",
        )

    def _create_note_invitation(self, expiration_time=1440):
        return NoteInvitation.create(
            expiration_time=expiration_time,
            recipient=self.recipient,
            recipient_email=self.recipient.email,
            inviter_id=self.sender.id,
            note_id=self.note.id,
        )

    def test_get_note_by_key_allows_unauthenticated_read_of_active_invite(self):
        # Arrange
        invite = self._create_note_invitation()
        self.client.force_authenticate(user=None)

        # Act
        response = self.client.get(f"/api/note/{invite.key}/get_note_by_key/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["note"]["id"], self.note.id)
        self.assertEqual(response.data["note"]["title"], "Shared note")
        self.assertEqual(
            response.data["note"]["latest_version"]["plain_text"],
            "Readable note body",
        )

    def test_get_note_by_key_rejects_expired_invite(self):
        # Arrange
        invite = self._create_note_invitation(expiration_time=-1)
        self.client.force_authenticate(user=None)

        # Act
        response = self.client.get(f"/api/note/{invite.key}/get_note_by_key/")

        # Assert
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data, {"data": "Invitation has expired"})
