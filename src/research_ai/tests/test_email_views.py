from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import ExpertSearch, GeneratedEmail
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


def _make_expert_search(created_by, expert_results=None):
    return ExpertSearch.objects.create(
        created_by=created_by,
        name="Test Search",
        query="ML",
        input_type=ExpertSearch.InputType.CUSTOM_QUERY,
        status=ExpertSearch.Status.COMPLETED,
        progress=100,
        expert_results=expert_results or [],
    )


class GenerateEmailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/generate-email/"
        self.expert_search = _make_expert_search(
            self.moderator,
            expert_results=[
                {
                    "name": "Dr. Jane Smith",
                    "email": "jane@example.com",
                    "title": "Professor",
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
            expert_results=[
                {
                    "name": "Dr. A",
                    "email": "a@example.com",
                    "title": "",
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
        self.assertNotIn("use_llm", call_kw)

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

    def test_get_returns_200_for_other_users_email(self):
        """Generated emails are shared: any editor can retrieve any email."""
        email = self._create_email(created_by=self.user)
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            f"/api/research_ai/expert-finder/emails/{email.id}/"
        )
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
            expert_results=[
                {
                    "name": "Dr. A",
                    "email": "a@x.com",
                    "title": "",
                    "affiliation": "",
                    "expertise": "",
                    "notes": "",
                },
                {
                    "name": "Dr. B",
                    "email": "b@x.com",
                    "title": "",
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

    @patch("research_ai.services.email_sending_service.send_mail")
    def test_send_plain_email_calls_send_mail_with_plain_and_html(self, mock_send_mail):
        send_plain_email(
            ["to@example.com"],
            "Subject",
            "<p>Hello</p>",
            reply_to=None,
            cc=None,
            from_email=None,
        )
        mock_send_mail.assert_called_once()
        # send_mail(subject, message, from_email, recipient_list, ...)
        call_args = mock_send_mail.call_args[0]
        self.assertIn("Subject", call_args[0])
        self.assertIn("Hello", call_args[1])
        self.assertEqual(call_args[3], ["to@example.com"])
        self.assertEqual(mock_send_mail.call_args[1]["html_message"], "<p>Hello</p>")

    @patch("research_ai.services.email_sending_service.EmailMultiAlternatives")
    def test_send_plain_email_with_reply_to_uses_email_multi_alternatives(
        self, mock_email_alt
    ):
        send_plain_email(
            ["to@example.com"],
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
            {"generated_email_ids": [email_rec.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.json().get("detail", "").lower())

    @patch("research_ai.views.email_views.send_plain_email")
    def test_preview_by_ids_sends_to_current_user(self, mock_send):
        email_rec = GeneratedEmail.objects.create(
            created_by=self.moderator,
            expert_name="Dr. X",
            email_subject="Subj",
            email_body="Body text",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"generated_email_ids": [email_rec.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("sent"), 1)
        mock_send.assert_called_once()
        call_kw = mock_send.call_args[1]
        self.assertEqual(call_kw["reply_to"], self.moderator.email)
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
        mock_send.assert_called_once()
