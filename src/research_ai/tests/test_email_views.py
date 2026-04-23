from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import (
    EmailTemplate,
    Expert,
    ExpertSearch,
    GeneratedEmail,
    SearchExpert,
)
from research_ai.services.email_sending_service import send_plain_email
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
        self.assertEqual(
            _normalize_template("  collaboration  "), ("collaboration", None)
        )
        self.assertEqual(
            _normalize_template("  custom:  my case  "),
            ("custom", "my case"),
        )


def _make_expert_search(created_by, expert_rows=None):
    search = ExpertSearch.objects.create(
        created_by=created_by,
        name="Test Search",
        query="ML",
        input_type=ExpertSearch.InputType.CUSTOM_QUERY,
        status=ExpertSearch.Status.COMPLETED,
        progress=100,
    )
    if not expert_rows:
        return search
    for i, row in enumerate(expert_rows):
        ex = Expert.objects.create(
            email=(row["email"] or "").strip().lower(),
            honorific=row.get("honorific") or "",
            first_name=row.get("first_name") or "",
            middle_name=row.get("middle_name") or "",
            last_name=row.get("last_name") or "",
            name_suffix=row.get("name_suffix") or "",
            academic_title=row.get("academic_title") or row.get("title") or "",
            affiliation=row.get("affiliation") or "",
            expertise=row.get("expertise") or "",
            notes=row.get("notes") or "",
        )
        SearchExpert.objects.create(expert_search=search, expert=ex, position=i)
    return search


class GenerateEmailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/generate-email/"
        self.expert_search = _make_expert_search(
            self.moderator,
            expert_rows=[
                {
                    "email": "jane@example.com",
                    "honorific": "Dr",
                    "first_name": "Jane",
                    "middle_name": "Marie",
                    "last_name": "Smith",
                    "academic_title": "Professor",
                    "affiliation": "MIT",
                    "expertise": "ML",
                    "notes": "",
                },
            ],
        )

    def test_post_requires_authentication(self):
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_expert_search_id_and_email_required(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"template": "collaboration"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_success_creates_record_and_returns_201(self, mock_generate):
        mock_generate.return_value = ("Subject here", "Body here")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(
            data["expert_name"],
            "Dr. Jane Marie Smith",
            msg="Stored name matches structured salutation (honorific + first + middle + last)",
        )
        self.assertEqual(data["expert_title"], "Professor")
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
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": "collaboration",
            },
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
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": "consultation",
            },
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
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("LLM unavailable", response.json().get("detail", ""))

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_with_expert_search_id_links_record(self, mock_generate):
        mock_generate.return_value = ("S", "B")
        search = _make_expert_search(
            self.moderator,
            expert_rows=[
                {
                    "email": "a@example.com",
                    "honorific": "Dr",
                    "first_name": "A",
                    "academic_title": "",
                    "affiliation": "",
                    "expertise": "",
                    "notes": "",
                },
            ],
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": search.id,
                "expert_email": "a@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rec = GeneratedEmail.objects.get()
        self.assertEqual(rec.expert_search_id, search.id)

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_with_template_id_passes_template_id_and_user(self, mock_generate):
        mock_generate.return_value = ("S", "B")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": "collaboration",
                "template_id": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        call_kw = mock_generate.call_args[1]
        self.assertEqual(call_kw["template_id"], 1)
        self.assertEqual(call_kw["user"], self.moderator)
        self.assertEqual(call_kw["template"], "collaboration")

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_template_null_requires_template_id(self, mock_generate):
        mock_generate.return_value = ("S", "B")
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_post_template_null_with_template_id_fixed_path(self, mock_generate):
        mock_generate.return_value = ("S", "B")
        t = EmailTemplate.objects.create(
            created_by=self.moderator,
            name="Var",
            email_subject="{{expert.name}}",
            email_body="Hi",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "jane@example.com",
                "template": None,
                "template_id": t.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        call_kw = mock_generate.call_args[1]
        self.assertIsNone(call_kw["template"])
        self.assertEqual(call_kw["template_id"], t.id)

    def test_post_with_invalid_expert_search_id_returns_404(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": 999999,
                "expert_email": "jane@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("not found", response.json().get("detail", "").lower())

    def test_post_expert_not_in_search_results_returns_400(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "expert_email": "unknown@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Expert not found", response.json().get("detail", ""))


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

    def test_get_filter_by_search_id(self):
        search_a = _make_expert_search(self.moderator)
        search_b = _make_expert_search(self.moderator)
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search_a,
            expert_name="Dr. A",
            email_subject="",
            email_body="",
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search_a,
            expert_name="Dr. A2",
            email_subject="",
            email_body="",
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search_b,
            expert_name="Dr. B",
            email_subject="",
            email_body="",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url + f"?search_id={search_a.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["emails"]), 2)
        names = {e["expert_name"] for e in data["emails"]}
        self.assertEqual(names, {"Dr. A", "Dr. A2"})

    def test_get_filter_by_search_id_invalid_returns_empty(self):
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. One",
            email_subject="",
            email_body="",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url + "?search_id=notanint")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(len(data["emails"]), 0)

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
        response = self.client.get(f"/api/research_ai/expert-finder/emails/{email.id}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_requires_moderator(self):
        self.client.force_authenticate(self.user)
        email = self._create_email()
        response = self.client.get(f"/api/research_ai/expert-finder/emails/{email.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_returns_200_for_own_email(self):
        email = self._create_email()
        self.client.force_authenticate(self.moderator)
        response = self.client.get(f"/api/research_ai/expert-finder/emails/{email.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], email.id)
        self.assertEqual(response.json()["expert_name"], "Dr. Test")

    def test_get_includes_list_navigation_single_email_in_search(self):
        search = _make_expert_search(self.moderator)
        email = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_name="Only",
            email_subject="",
            email_body="",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(f"/api/research_ai/expert-finder/emails/{email.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        nav = response.json()["list_navigation"]
        self.assertEqual(nav["total"], 1)
        self.assertEqual(nav["position"], 1)
        self.assertIsNone(nav["previous_id"])
        self.assertIsNone(nav["next_id"])

    def test_get_list_navigation_matches_list_order_for_search(self):
        search = _make_expert_search(self.moderator)
        other_search = _make_expert_search(self.moderator)
        base = timezone.now()
        newest = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_name="Newest",
            email_subject="",
            email_body="",
        )
        mid = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_name="Mid",
            email_subject="",
            email_body="",
        )
        oldest = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=search,
            expert_name="Oldest",
            email_subject="",
            email_body="",
        )
        GeneratedEmail.objects.filter(pk=newest.pk).update(created_date=base)
        GeneratedEmail.objects.filter(pk=mid.pk).update(
            created_date=base - timedelta(hours=1)
        )
        GeneratedEmail.objects.filter(pk=oldest.pk).update(
            created_date=base - timedelta(hours=2)
        )
        GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_search=other_search,
            expert_name="Other search",
            email_subject="",
            email_body="",
        )
        self.client.force_authenticate(self.moderator)

        r_mid = self.client.get(f"/api/research_ai/expert-finder/emails/{mid.id}/")
        nav = r_mid.json()["list_navigation"]
        self.assertEqual(nav["total"], 3)
        self.assertEqual(nav["position"], 2)
        self.assertEqual(nav["previous_id"], newest.id)
        self.assertEqual(nav["next_id"], oldest.id)

        r_new = self.client.get(f"/api/research_ai/expert-finder/emails/{newest.id}/")
        nav_new = r_new.json()["list_navigation"]
        self.assertEqual(nav_new["position"], 1)
        self.assertIsNone(nav_new["previous_id"])
        self.assertEqual(nav_new["next_id"], mid.id)

        r_old = self.client.get(f"/api/research_ai/expert-finder/emails/{oldest.id}/")
        nav_old = r_old.json()["list_navigation"]
        self.assertEqual(nav_old["position"], 3)
        self.assertEqual(nav_old["previous_id"], mid.id)
        self.assertIsNone(nav_old["next_id"])

    def test_get_list_navigation_without_expert_search_uses_global_sequence(self):
        base = timezone.now()
        first = self._create_email()
        second = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Second",
            email_subject="",
            email_body="",
        )
        GeneratedEmail.objects.filter(pk=first.pk).update(created_date=base)
        GeneratedEmail.objects.filter(pk=second.pk).update(
            created_date=base - timedelta(hours=1)
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(f"/api/research_ai/expert-finder/emails/{second.id}/")
        nav = r.json()["list_navigation"]
        self.assertEqual(nav["total"], 2)
        self.assertEqual(nav["position"], 2)
        self.assertEqual(nav["previous_id"], first.id)
        self.assertIsNone(nav["next_id"])

    def test_get_returns_404_for_nonexistent(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get("/api/research_ai/expert-finder/emails/999999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_returns_200_for_other_users_email(self):
        """Generated emails are shared: any editor can retrieve any email."""
        email = self._create_email(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.get(f"/api/research_ai/expert-finder/emails/{email.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], email.id)

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

    def test_patch_can_set_status_closed(self):
        email = self._create_email()
        self.client.force_authenticate(self.moderator)
        response = self.client.patch(
            f"/api/research_ai/expert-finder/emails/{email.id}/",
            {"status": "closed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "closed")
        email.refresh_from_db()
        self.assertEqual(email.status, "closed")

    def test_patch_status_sent_sets_expert_last_email_sent_at(self):
        addr = "manual-sent-patch@example.com"
        expert = Expert.objects.create(
            email=addr,
            first_name="Pat",
            last_name="Expert",
        )
        email = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_email=addr,
            expert_name="Dr. Pat",
            email_subject="S",
            email_body="B",
            status=GeneratedEmail.Status.DRAFT,
        )
        self.assertIsNone(expert.last_email_sent_at)
        self.client.force_authenticate(self.moderator)
        before = timezone.now()
        response = self.client.patch(
            f"/api/research_ai/expert-finder/emails/{email.id}/",
            {"status": "sent"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expert.refresh_from_db()
        self.assertIsNotNone(expert.last_email_sent_at)
        self.assertGreaterEqual(expert.last_email_sent_at, before)

    def test_patch_returns_200_for_other_users_email(self):
        """Generated emails are shared: any editor can update any email."""
        email = self._create_email(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.patch(
            f"/api/research_ai/expert-finder/emails/{email.id}/",
            {"email_body": "Updated By Moderator"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        email.refresh_from_db()
        self.assertEqual(email.email_body, "Updated By Moderator")

    def test_delete_returns_204_and_removes_record(self):
        email = self._create_email()
        self.client.force_authenticate(self.moderator)
        response = self.client.delete(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GeneratedEmail.objects.filter(pk=email.id).exists())

    def test_delete_returns_204_for_other_users_email(self):
        """Generated emails are shared: any editor can delete any email."""
        email = self._create_email(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.delete(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GeneratedEmail.objects.filter(pk=email.id).exists())


class BulkGenerateEmailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.url = "/api/research_ai/expert-finder/generate-emails-bulk/"
        self.expert_search = _make_expert_search(
            self.moderator,
            expert_rows=[
                {
                    "email": "a@x.com",
                    "honorific": "Dr",
                    "first_name": "A",
                    "academic_title": "",
                    "affiliation": "",
                    "expertise": "",
                    "notes": "",
                },
                {
                    "email": "b@x.com",
                    "honorific": "Dr",
                    "first_name": "B",
                    "academic_title": "",
                    "affiliation": "",
                    "expertise": "",
                    "notes": "",
                },
            ],
        )

    def test_post_requires_authentication(self):
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "experts": [{"expert_email": "a@x.com"}],
                "template": "rfp-outreach",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("research_ai.views.email_views.process_bulk_generate_emails_task")
    def test_post_creates_placeholders_and_returns_202(self, mock_task):
        mock_task.delay.return_value = None
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "experts": [{"expert_email": "a@x.com"}, {"expert_email": "b@x.com"}],
                "template": "rfp-outreach",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertIn("emails", data)
        self.assertIn("ids", data)
        self.assertEqual(len(data["emails"]), 2)
        self.assertEqual(len(data["ids"]), 2)
        self.assertEqual(GeneratedEmail.objects.filter(status="processing").count(), 2)
        mock_task.delay.assert_called_once()

    def test_post_template_null_without_template_id_returns_400(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "experts": [{"expert_email": "a@x.com"}],
                "template": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("research_ai.views.email_views.process_bulk_generate_emails_task")
    def test_post_template_null_stores_null_template_on_placeholder(self, mock_task):
        mock_task.delay.return_value = None
        t = EmailTemplate.objects.create(
            created_by=self.moderator,
            name="Bulk var",
            email_subject="S",
            email_body="B",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "experts": [{"expert_email": "a@x.com"}],
                "template": None,
                "template_id": t.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        rec = GeneratedEmail.objects.get(expert_email="a@x.com")
        self.assertIsNone(rec.template)

    def test_post_expert_not_in_search_returns_400_and_creates_no_placeholders(self):
        """Invalid expert email returns 400 and no GeneratedEmail records (transaction rollback)."""
        self.client.force_authenticate(self.moderator)
        initial_count = GeneratedEmail.objects.count()
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "experts": [{"expert_email": "not-in-search@x.com"}],
                "template": "rfp-outreach",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Expert not found", response.json().get("detail", ""))
        self.assertEqual(GeneratedEmail.objects.count(), initial_count)

    @patch("research_ai.views.email_views.process_bulk_generate_emails_task")
    def test_post_second_expert_invalid_rolls_back_all_placeholders(self, mock_task):
        """When second expert is invalid, no placeholders are created (atomic rollback)."""
        self.client.force_authenticate(self.moderator)
        initial_count = GeneratedEmail.objects.count()
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.expert_search.id,
                "experts": [
                    {"expert_email": "a@x.com"},
                    {"expert_email": "not-in-search@x.com"},
                ],
                "template": "rfp-outreach",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(GeneratedEmail.objects.count(), initial_count)
        mock_task.delay.assert_not_called()


class SendPlainEmailTests(APITestCase):
    """Unit tests for send_plain_email service."""

    @patch("research_ai.services.email_sending_service.EmailMultiAlternatives")
    def test_send_plain_email_calls_send_mail_with_plain_and_html(self, mock_email_alt):
        mock_instance = mock_email_alt.return_value
        mock_instance.extra_headers = {"message_id": "messageId1"}
        ses_message_id = send_plain_email(
            "to@example.com",
            "Subject",
            "<p>Hello</p>",
            reply_to=None,
            cc=None,
            from_email=None,
        )
        mock_email_alt.assert_called_once()
        call_kwargs = mock_email_alt.call_args[1]
        self.assertIn("Subject", call_kwargs["subject"])
        self.assertIn("Hello", call_kwargs["body"])
        self.assertEqual(call_kwargs["to"], ["to@example.com"])
        mock_instance.attach_alternative.assert_called_once_with(
            "<p>Hello</p>", "text/html"
        )
        mock_instance.send.assert_called_once()
        self.assertEqual(ses_message_id, "messageId1")

    @patch("research_ai.services.email_sending_service.EmailMultiAlternatives")
    def test_send_plain_email_with_reply_to_uses_email_multi_alternatives(
        self, mock_email_alt
    ):
        send_plain_email(
            "to@example.com",
            "Subject",
            "Body",
            reply_to="reply@example.com",
            cc=None,
            from_email=None,
        )
        mock_email_alt.return_value.attach_alternative.assert_called_once()
        mock_email_alt.return_value.send.assert_called_once()


class PreviewEmailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.url = "/api/research_ai/expert-finder/emails/preview/"

    def test_preview_user_no_email_returns_400(self):
        """When request.user has no email, preview returns 400."""
        user = create_random_authenticated_user("noemail", moderator=True)
        user.email = ""
        user.save(update_fields=["email"])
        email_rec = GeneratedEmail.objects.create(
            created_by=user,
            expert_name="Dr. X",
            email_subject="Subj",
            email_body="Body",
        )
        self.client.force_authenticate(user)
        response = self.client.post(
            self.url,
            {
                "generated_email_ids": [email_rec.id],
                "reply_to": "replies@example.com",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.json().get("detail", "").lower())

    def test_preview_without_reply_to_returns_400(self):
        email_rec = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. X",
            email_subject="Subj",
            email_body="Body",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"generated_email_ids": [email_rec.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reply_to", response.json())

    @patch("research_ai.views.email_views.send_plain_email")
    def test_preview_by_ids_sends_to_current_user(self, mock_send):
        reply_to_email = "sender-replies@example.com"
        email_rec = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. X",
            email_subject="Subj",
            email_body="Body text",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "generated_email_ids": [email_rec.id],
                "reply_to": reply_to_email,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("sent"), 1)
        mock_send.assert_called_once()
        call_kw = mock_send.call_args[1]
        self.assertEqual(call_kw["reply_to"], reply_to_email)
        self.assertIn(settings.EXPERT_FINDER_FROM_EMAIL, call_kw["from_email"])


class SendEmailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.url = "/api/research_ai/expert-finder/emails/send/"

    def test_send_without_reply_to_returns_400(self):
        """Send endpoint requires reply_to in request body."""
        email_rec = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. Y",
            expert_email="expert@example.com",
            email_subject="Subj",
            email_body="Body",
            status="draft",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"generated_email_ids": [email_rec.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reply_to", response.json())

    @patch("research_ai.views.email_views.send_queued_emails_task")
    def test_send_queues_emails_and_returns_immediately(self, mock_task):
        reply_to_email = "reply@example.com"
        email_rec = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. Y",
            expert_email="expert@example.com",
            email_subject="Subj",
            email_body="Body",
            status="draft",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "generated_email_ids": [email_rec.id],
                "reply_to": reply_to_email,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("sent"), 1)
        email_rec.refresh_from_db()
        self.assertEqual(email_rec.status, "sending")
        mock_task.delay.assert_called_once()
        call_kw = mock_task.delay.call_args[1]
        self.assertEqual(call_kw["generated_email_ids"], [email_rec.id])
        self.assertEqual(call_kw["reply_to"], reply_to_email)
        from_email = call_kw["from_email"]
        self.assertIn("ResearchHub", from_email)
        self.assertIn(settings.EXPERT_FINDER_FROM_EMAIL, from_email)

    @patch("research_ai.tasks.send_plain_email")
    def test_send_queued_emails_task_sends_and_updates_status(self, mock_send):
        from research_ai.tasks import send_queued_emails_task

        mock_send.return_value = "ses-msg-id-123"
        email_rec = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. Y",
            expert_email="expert@example.com",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENDING,
        )
        result = send_queued_emails_task.apply(
            kwargs={
                "generated_email_ids": [email_rec.id],
                "reply_to": None,
                "cc": None,
                "from_email": None,
            }
        ).get()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["failed"], 0)
        email_rec.refresh_from_db()
        self.assertEqual(email_rec.status, "sent")
        self.assertEqual(email_rec.ses_message_id, "ses-msg-id-123")
        mock_send.assert_called_once()
