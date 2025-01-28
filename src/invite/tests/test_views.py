from allauth.utils import get_user_model

from invite.related_models.note_invitation import NoteInvitation
from invite.related_models.organization_invitation import OrganizationInvitation
from utils.test_helpers import APITestCaseWithOrg


class OrganizationInvitationViewsTest(APITestCaseWithOrg):
    def setUp(self):
        # Create + auth user
        self.sender = get_user_model().objects.create_user(
            username="user1@researchhub_test.com",
            password="password",
            email="user1@researchhub_test.com",
        )
        self.recipient = get_user_model().objects.create_user(
            username="user2@researchhub_test.com",
            password="password",
            email="user2@researchhub_test.com",
        )

        # Create org
        self.client.force_authenticate(self.sender)
        response = self.client.post("/api/organization/", {"name": "ORG A"})
        self.org = response.data

    def test_list_invites_sender(self):
        response = OrganizationInvitation.create(
            expiration_time=1440,
            recipient=self.recipient,
            inviter_id=self.sender.id,
            organization_id=self.org["id"],
        )

        # Get org invite as sender
        response = self.client.get("/api/invite/organization/")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data["results"]), 0)

    def test_list_invites_receiver(self):
        response = OrganizationInvitation.create(
            expiration_time=1440,
            recipient=self.recipient,
            inviter_id=self.sender.id,
            organization_id=self.org["id"],
        )

        # Get org invite as recipient
        self.client.force_authenticate(self.recipient)
        response = self.client.get("/api/invite/organization/")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data["results"]), 1)


class NoteInvitationViewsTest(APITestCaseWithOrg):
    def setUp(self):
        # Create + auth user
        self.sender = get_user_model().objects.create_user(
            username="user1@researchhub_test.com",
            password="password",
            email="user1@researchhub_test.com",
        )
        self.recipient = get_user_model().objects.create_user(
            username="user2@researchhub_test.com",
            password="password",
            email="user2@researchhub_test.com",
        )

        # Create note
        self.client.force_authenticate(self.sender)
        response = self.client.post("/api/note/", {"name": "NOTE A"})
        self.org = response.data

    def test_list_invites_sender(self):
        response = NoteInvitation.create(
            expiration_time=1440,
            recipient=self.recipient,
            inviter_id=self.sender.id,
            note_id=self.org["id"],
        )

        # Get note invite as sender
        response = self.client.get("/api/invite/note/")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data["results"]), 0)

    def test_list_invites_receiver(self):
        response = NoteInvitation.create(
            expiration_time=1440,
            recipient=self.recipient,
            inviter_id=self.sender.id,
            note_id=self.org["id"],
        )

        # Get note invite as recipient
        self.client.force_authenticate(self.recipient)
        response = self.client.get("/api/invite/note/")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(response.data["results"]), 1)
