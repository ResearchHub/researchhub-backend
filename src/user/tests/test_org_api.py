import uuid

from allauth.utils import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from researchhub_access_group.models import Permission
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import Organization


class OrganizationTests(APITestCase):
    def setUp(self):
        # Create + auth user
        self.org_a_admin = get_user_model().objects.create_user(
            username="admin@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="admin@researchhub_test.com",
        )
        self.org_a_member_user = get_user_model().objects.create_user(
            username="test1@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="test1@researchhub_test.com",
        )
        self.org_b_admin = get_user_model().objects.create_user(
            username="org_b_admin@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="org_b_admin@researchhub_test.com",
        )
        self.note_b_user = get_user_model().objects.create_user(
            username="test2@researchhub_test.com",
            password=uuid.uuid4().hex,
            email="test2@researchhub_test.com",
        )
        self.client.force_authenticate(self.org_a_admin)

        # Create org A
        response = self.client.post("/api/organization/", {"name": "ORG A"})
        self.org_a = response.data

        # Create org B
        self.client.force_authenticate(self.org_b_admin)
        response = self.client.post("/api/organization/", {"name": "ORG B"})
        self.org_b = response.data

        # Create note in org B
        self.client.force_authenticate(self.org_b_admin)
        response = self.client.post(
            "/api/note/", {"name": "NOTE B", "organization_slug": self.org_b["slug"]}
        )
        self.note = response.data

        # Add note_b_user to note in org B document permissions
        Permission.objects.create(
            # created_by=self.org_b_admin,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note["unified_document"]["id"],
            # updated_by=self.org_b_admin,
            user=self.note_b_user,
        )

        # Add second user
        Permission.objects.create(
            access_type="MEMBER",
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.org_a["id"],
            user=self.org_a_member_user,
        )

    def test_get_organization_users(self):
        self.client.force_authenticate(self.org_a_admin)

        response = self.client.get(
            f"/api/organization/{self.org_a['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 2)

    def test_list(self):
        self.client.force_authenticate(self.org_a_member_user)

        response = self.client.get("/api/organization/")
        self.assertEqual(response.status_code, 200)

        # Ensure that the user is only a member of their default org and org A.
        self.assertEqual(len(response.data["results"]), 2)

    def test_list_access_to_note_but_not_org(self):
        self.client.force_authenticate(self.note_b_user)

        response = self.client.get("/api/organization/")
        self.assertEqual(response.status_code, 200)

        # Ensure that the user is only a member of their default org and org B
        # (they have a permission on a note within org B).
        self.assertEqual(len(response.data["results"]), 2)

    def test_member_cannot_invite_others(self):
        self.client.force_authenticate(self.org_a_member_user)

        response = self.client.post(
            f"/api/organization/{self.org_a['id']}/invite_user/",
            {"access_type": "MEMBER", "email": "email@researchhub_test.com"},
        )
        self.assertEqual(response.status_code, 403)

        # Refetch org members list and ensure it did not grow
        response = self.client.get(
            f"/api/organization/{self.org_a['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 2)

    def test_admin_can_invite_others(self):
        self.client.force_authenticate(self.org_a_admin)

        response = self.client.post(
            f"/api/organization/{self.org_a['id']}/invite_user/",
            {"access_type": "MEMBER", "email": "email@researchhub_test.com"},
        )
        self.assertEqual(response.status_code, 200)

        # Refetch org members list and ensure it grew
        response = self.client.get(
            f"/api/organization/{self.org_a['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 3)

    def test_admin_of_org_B_cannot_update_details_of_org_A(self):
        self.client.force_authenticate(self.org_b_admin)

        # Update name of ORG A
        response = self.client.patch(
            f"/api/organization/{self.org_a['id']}/", {"name": "updated name"}
        )
        self.assertEqual(response.status_code, 404)

        # Ensure that the org was not updated
        self.client.force_authenticate(self.org_a_admin)
        response = self.client.get(f"/api/organization/{self.org_a['id']}/")
        self.assertNotEqual(response.data["name"], "updated name")

    def test_admin_of_org_B_cannot_invite_users_in_org_A(self):
        self.client.force_authenticate(self.org_b_admin)

        # Org B Admin tries to invite user to org A
        response = self.client.post(
            f"/api/organization/{self.org_a['id']}/invite_user/",
            {"access_type": "MEMBER", "email": "email@researchhub_test.com"},
        )
        self.assertEqual(response.status_code, 404)

        # Refetch org A members list and ensure it did not grow, reauth as org A admin to access.
        self.client.force_authenticate(self.org_a_admin)
        response = self.client.get(
            f"/api/organization/{self.org_a['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 2)

    def test_admin_of_org_B_cannot_create_notes_in_org_A(self):
        self.client.force_authenticate(self.org_b_admin)

        # Update name of ORG A
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org_a["slug"],
                "title": "TEST",
            },
        )
        self.assertEqual(response.status_code, 403)
