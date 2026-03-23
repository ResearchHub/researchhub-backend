from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import EmailTemplate
from user.tests.helpers import create_random_authenticated_user


class TemplateListViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/templates/"

    def test_get_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_returns_list_with_pagination(self):
        EmailTemplate.objects.create(
            created_by=self.moderator,
            name="My Template",
            contact_name="Jane",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("templates", data)
        self.assertIn("total", data)
        self.assertIn("limit", data)
        self.assertIn("offset", data)
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["templates"]), 1)
        self.assertEqual(data["templates"][0]["name"], "My Template")
        self.assertEqual(data["templates"][0]["contact_name"], "Jane")

    def test_get_respects_limit_and_offset(self):
        for i in range(5):
            EmailTemplate.objects.create(
                created_by=self.moderator,
                name=f"Template {i}",
            )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url + "?limit=2&offset=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["limit"], 2)
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["templates"]), 2)

    def test_get_returns_all_templates_shared(self):
        """Templates are shared: all editors/moderators see every template."""
        EmailTemplate.objects.create(
            created_by=self.moderator,
            name="Mine",
        )
        EmailTemplate.objects.create(
            created_by=self.user,
            name="Theirs",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["total"], 2)
        names = {t["name"] for t in response.json()["templates"]}
        self.assertEqual(names, {"Mine", "Theirs"})

    def test_post_requires_authentication(self):
        response = self.client.post(
            self.url,
            {"name": "New Template"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            {"name": "New Template"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_creates_template_returns_201(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "name": "Conference Invite",
                "contact_name": "Jane Doe",
                "contact_title": "Prof",
                "contact_institution": "MIT",
                "contact_email": "jane@mit.edu",
                "outreach_context": "Annual conference 2025",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], "Conference Invite")
        self.assertEqual(data["contact_name"], "Jane Doe")
        self.assertEqual(data["contact_institution"], "MIT")
        self.assertEqual(data["outreach_context"], "Annual conference 2025")
        self.assertEqual(EmailTemplate.objects.count(), 1)
        t = EmailTemplate.objects.get()
        self.assertEqual(t.created_by, self.moderator)

    def test_post_name_required(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"contact_name": "Jane"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TemplateDetailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)

    def _create_template(self, created_by=None, name="Test Template"):
        created_by = created_by or self.moderator
        return EmailTemplate.objects.create(
            created_by=created_by,
            name=name,
            contact_name="Jane",
            contact_institution="MIT",
        )

    def test_get_requires_authentication(self):
        t = self._create_template()
        response = self.client.get(
            f"/api/research_ai/expert-finder/templates/{t.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_requires_moderator(self):
        self.client.force_authenticate(self.user)
        t = self._create_template()
        response = self.client.get(
            f"/api/research_ai/expert-finder/templates/{t.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_returns_200_for_own_template(self):
        t = self._create_template(name="My Template")
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            f"/api/research_ai/expert-finder/templates/{t.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], t.id)
        self.assertEqual(data["name"], "My Template")
        self.assertEqual(data["contact_institution"], "MIT")

    def test_get_returns_404_for_nonexistent(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/templates/999999/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("not found", response.json().get("detail", "").lower())

    def test_get_returns_200_for_other_users_template(self):
        """Templates are shared: any editor can retrieve any template."""
        t = self._create_template(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            f"/api/research_ai/expert-finder/templates/{t.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], t.id)
        self.assertEqual(response.json()["name"], "Test Template")

    def test_patch_updates_and_returns_200(self):
        t = self._create_template(name="Original")
        self.client.force_authenticate(self.moderator)
        response = self.client.patch(
            f"/api/research_ai/expert-finder/templates/{t.id}/",
            {"name": "Updated Name", "contact_email": "new@mit.edu"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["name"], "Updated Name")
        self.assertEqual(data["contact_email"], "new@mit.edu")
        t.refresh_from_db()
        self.assertEqual(t.name, "Updated Name")
        self.assertEqual(t.contact_email, "new@mit.edu")

    def test_patch_returns_200_for_other_users_template(self):
        """Templates are shared: any editor can update any template."""
        t = self._create_template(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.patch(
            f"/api/research_ai/expert-finder/templates/{t.id}/",
            {"name": "Updated By Moderator"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        t.refresh_from_db()
        self.assertEqual(t.name, "Updated By Moderator")

    def test_delete_returns_204_and_removes_template(self):
        t = self._create_template()
        self.client.force_authenticate(self.moderator)
        response = self.client.delete(
            f"/api/research_ai/expert-finder/templates/{t.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(EmailTemplate.objects.filter(pk=t.id).exists())

    def test_delete_returns_204_for_other_users_template(self):
        """Templates are shared: any editor can delete any template."""
        t = self._create_template(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.delete(
            f"/api/research_ai/expert-finder/templates/{t.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(EmailTemplate.objects.filter(pk=t.id).exists())
