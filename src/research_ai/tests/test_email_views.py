from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.views.email_views import _normalize_template
from user.tests.helpers import create_random_authenticated_user


class NormalizeTemplateTests(APITestCase):
    def test_valid_key_returns_key_and_none(self):
        self.assertEqual(_normalize_template("collaboration"), ("collaboration", None))
        self.assertEqual(_normalize_template("peer-review"), ("peer-review", None))

    def test_custom_prefix_returns_custom_and_use_case(self):
        self.assertEqual(
            _normalize_template("custom: conference invite"),
            ("custom", "conference invite"),
        )
        self.assertEqual(_normalize_template("custom:"), ("custom", None))

    def test_unknown_key_treated_as_custom_use_case(self):
        self.assertEqual(_normalize_template("other"), ("custom", "other"))
        self.assertEqual(_normalize_template(""), ("custom", None))

    def test_strips_whitespace(self):
        self.assertEqual(_normalize_template("  collaboration  "), ("collaboration", None))
        self.assertEqual(
            _normalize_template("  custom:  my case  "),
            ("custom", "my case"),
        )


class GenerateEmailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/generate-email/"

    def test_post_requires_authentication(self):
        response = self.client.post(
            self.url,
            {"expert_name": "Dr. Smith", "template": "collaboration"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            {"expert_name": "Dr. Smith", "template": "collaboration"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_expert_name_required(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"expert_name": "", "template": "collaboration"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertTrue(
            "expert_name" in data or "expert_name" in data.get("detail", ""),
            "Response should indicate expert_name error",
        )

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_success_creates_record_and_returns_201(self, mock_generate):
        mock_generate.return_value = ("Subject here", "Body here")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_name": "Dr. Jane Smith",
                "template": "collaboration",
                "expert_title": "Professor",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["expert_name"], "Dr. Jane Smith")
        self.assertEqual(data["email_subject"], "Subject here")
        self.assertEqual(data["email_body"], "Body here")
        self.assertEqual(data["status"], "draft")
        self.assertEqual(GeneratedEmail.objects.count(), 1)
        rec = GeneratedEmail.objects.get()
        self.assertEqual(rec.created_by, self.moderator)

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_save_false_returns_subject_body_only(self, mock_generate):
        mock_generate.return_value = ("Subj", "Body text")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url + "?save=false",
            {"expert_name": "Dr. X", "template": "collaboration"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["subject"], "Subj")
        self.assertEqual(data["body"], "Body text")
        self.assertEqual(GeneratedEmail.objects.count(), 0)

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_action_generate_returns_subject_body_only(self, mock_generate):
        mock_generate.return_value = ("A", "B")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url + "?action=generate",
            {"expert_name": "Dr. Y", "template": "consultation"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"subject": "A", "body": "B"})
        self.assertEqual(GeneratedEmail.objects.count(), 0)

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_runtime_error_returns_503(self, mock_generate):
        mock_generate.side_effect = RuntimeError("LLM unavailable")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"expert_name": "Dr. Z", "template": "collaboration"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("LLM unavailable", response.json().get("detail", ""))

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_with_expert_search_id_links_record(self, mock_generate):
        mock_generate.return_value = ("S", "B")
        search = ExpertSearch.objects.create(
            created_by=self.moderator,
            name="Test Search",
            query="ML",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
            status=ExpertSearch.Status.COMPLETED,
            progress=100,
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_name": "Dr. A",
                "template": "collaboration",
                "expert_search_id": search.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rec = GeneratedEmail.objects.get()
        self.assertEqual(rec.expert_search_id, search.id)

    @patch("research_ai.views.email_views.get_email_template")
    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_with_template_id_uses_template_data(
        self, mock_generate, mock_get_template
    ):
        mock_generate.return_value = ("S", "B")
        mock_et = type("ET", (), {
            "contact_name": "Jane",
            "contact_title": "Prof",
            "contact_institution": "MIT",
            "contact_email": "j@mit.edu",
            "contact_phone": "",
            "contact_website": "",
            "outreach_context": "Conference invite",
        })()
        mock_get_template.return_value = mock_et
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_name": "Dr. T",
                "template": "collaboration",
                "template_id": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_get_template.assert_called_once_with(self.moderator, 1)
        call_kw = mock_generate.call_args[1]
        self.assertEqual(call_kw["template_data"]["contact_name"], "Jane")
        self.assertEqual(call_kw["template_data"]["contact_institution"], "MIT")
        self.assertEqual(call_kw["outreach_context"], "Conference invite")

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_with_invalid_expert_search_id_still_creates_email(self, mock_generate):
        mock_generate.return_value = ("S", "B")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_name": "Dr. B",
                "template": "collaboration",
                "expert_search_id": 999999,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rec = GeneratedEmail.objects.get()
        self.assertIsNone(rec.expert_search_id)


class GeneratedEmailListViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/emails/"

    def test_get_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_returns_list_with_pagination(self):
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. One",
            email_subject="S1",
            email_body="B1",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("emails", data)
        self.assertIn("total", data)
        self.assertIn("limit", data)
        self.assertIn("offset", data)
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["emails"]), 1)
        self.assertEqual(data["emails"][0]["expert_name"], "Dr. One")

    def test_get_respects_limit_and_offset(self):
        for i in range(5):
            GeneratedEmail.objects.create(
                created_by=self.moderator,
                expert_name=f"Dr. {i}",
                email_subject="",
                email_body="",
            )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url + "?limit=2&offset=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["limit"], 2)
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["emails"]), 2)

    def test_post_requires_authentication(self):
        response = self.client.post(
            self.url,
            {"expert_name": "Dr. New", "email_subject": "S", "email_body": "B"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_creates_draft_without_llm(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_name": "Dr. New",
                "email_subject": "My subject",
                "email_body": "My body",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["expert_name"], "Dr. New")
        self.assertEqual(data["email_subject"], "My subject")
        self.assertEqual(data["email_body"], "My body")
        self.assertEqual(data["status"], "draft")
        self.assertEqual(GeneratedEmail.objects.count(), 1)


class GeneratedEmailDetailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)

    def _create_email(self, created_by=None):
        created_by = created_by or self.moderator
        return GeneratedEmail.objects.create(
            created_by=created_by,
            expert_name="Dr. Test",
            email_subject="Subj",
            email_body="Body",
        )

    def test_get_requires_authentication(self):
        email = self._create_email()
        response = self.client.get(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_requires_moderator(self):
        self.client.force_authenticate(self.user)
        email = self._create_email()
        response = self.client.get(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_returns_200_for_own_email(self):
        email = self._create_email()
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], email.id)
        self.assertEqual(response.json()["expert_name"], "Dr. Test")

    def test_get_returns_404_for_nonexistent(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/emails/999999/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_returns_404_for_other_users_email(self):
        email = self._create_email(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_updates_and_returns_200(self):
        email = self._create_email()
        self.client.force_authenticate(self.moderator)
        response = self.client.patch(
            f"/api/research_ai/expert-finder/emails/{email.id}/",
            {"email_body": "Updated body"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        email.refresh_from_db()
        self.assertEqual(email.email_body, "Updated body")

    def test_patch_returns_404_for_other_users_email(self):
        email = self._create_email(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.patch(
            f"/api/research_ai/expert-finder/emails/{email.id}/",
            {"email_body": "Hacked"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        email.refresh_from_db()
        self.assertEqual(email.email_body, "Body")

    def test_delete_returns_204_and_removes_record(self):
        email = self._create_email()
        self.client.force_authenticate(self.moderator)
        response = self.client.delete(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GeneratedEmail.objects.filter(pk=email.id).exists())

    def test_delete_returns_404_for_other_users_email(self):
        email = self._create_email(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.delete(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(GeneratedEmail.objects.filter(pk=email.id).exists())
