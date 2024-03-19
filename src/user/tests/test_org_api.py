from allauth.utils import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from researchhub_access_group.models import Permission
from user.models import Organization


class OrganizationTests(APITestCase):
    def setUp(self):
        # Create + auth user
        self.admin_user = get_user_model().objects.create_user(
            username="admin@researchhub_test.com",
            password="password",
            email="admin@researchhub_test.com",
        )
        self.member_user = get_user_model().objects.create_user(
            username="test@researchhub_test.com",
            password="password",
            email="test@researchhub_test.com",
        )
        self.client.force_authenticate(self.admin_user)

        # Create org
        response = self.client.post("/api/organization/", {"name": "some org"})
        self.org = response.data

        # Add second user
        Permission.objects.create(
            access_type="MEMBER",
            content_type=ContentType.objects.get_for_model(Organization),
            object_id=self.org["id"],
            user=self.member_user,
        )

    def test_get_organization_users(self):
        response = self.client.get(
            f"/api/organization/{self.org['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 2)

    def test_member_cannot_invite_others(self):
        self.client.force_authenticate(self.member_user)

        response = self.client.post(
            f"/api/organization/{self.org['id']}/invite_user/",
            {"access_type": "MEMBER", "email": "email@researchhub_test.com"},
        )
        self.assertEqual(response.status_code, 403)

        # Refetch org members list and ensure it did not grow
        response = self.client.get(
            f"/api/organization/{self.org['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 2)

    def test_admin_can_invite_others(self):
        self.client.force_authenticate(self.admin_user)

        response = self.client.post(
            f"/api/organization/{self.org['id']}/invite_user/",
            {"access_type": "MEMBER", "email": "email@researchhub_test.com"},
        )
        self.assertEqual(response.status_code, 200)

        # Refetch org members list and ensure it grew
        response = self.client.get(
            f"/api/organization/{self.org['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 3)

    def test_admin_of_org_B_cannot_update_details_of_org_A(self):
        # Create + auth user
        self.org_b_admin = get_user_model().objects.create_user(
            username="org_b_admin@researchhub_test.com",
            password="password",
            email="org_b_admin@researchhub_test.com",
        )
        self.client.force_authenticate(self.org_b_admin)

        # Create org B
        response = self.client.post("/api/organization/", {"name": "ORG B"})

        # Update name of ORG A
        response = self.client.patch(
            f"/api/organization/{self.org['id']}/", {"name": "updated name"}
        )
        self.assertEqual(response.status_code, 403)

        # Ensure that the org was not updated
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(f"/api/organization/{self.org['id']}/")
        self.assertNotEqual(response.data["name"], "updated name")

    def test_admin_of_org_B_cannot_invite_users_in_org_A(self):
        # Create + auth user
        self.org_b_admin = get_user_model().objects.create_user(
            username="org_b_admin@researchhub_test.com",
            password="password",
            email="org_b_admin@researchhub_test.com",
        )
        self.client.force_authenticate(self.org_b_admin)

        # Create org B
        response = self.client.post("/api/organization/", {"name": "ORG B"})

        # Org B Admin tries to invite user to org A
        response = self.client.post(
            f"/api/organization/{self.org['id']}/invite_user/",
            {"access_type": "MEMBER", "email": "email@researchhub_test.com"},
        )
        self.assertEqual(response.status_code, 403)

        # Refetch org A members list and ensure it did not grow, reauth as org A admin to access.
        self.client.force_authenticate(self.admin_user)
        response = self.client.get(
            f"/api/organization/{self.org['id']}/get_organization_users/"
        )
        self.assertEqual(response.data["user_count"], 2)

    def test_admin_of_org_B_cannot_create_notes_in_org_A(self):
        # Create + auth user
        self.org_b_admin = get_user_model().objects.create_user(
            username="org_b_admin@researchhub_test.com",
            password="password",
            email="org_b_admin@researchhub_test.com",
        )
        self.client.force_authenticate(self.org_b_admin)

        # Create org B
        response = self.client.post("/api/organization/", {"name": "ORG B"})

        # Update name of ORG A
        response = self.client.post(
            "/api/note/",
            {
                "grouping": "WORKSPACE",
                "organization_slug": self.org["slug"],
                "title": "TEST",
            },
        )
        self.assertEqual(response.status_code, 403)
