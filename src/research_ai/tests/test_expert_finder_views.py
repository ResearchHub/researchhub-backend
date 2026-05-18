# Expert finder API view tests
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import Expert, ExpertSearch, GeneratedEmail, SearchExpert
from user.tests.helpers import create_random_authenticated_user


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ExpertSearchListCreateViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/searches/"

    def test_create_requires_authentication(self):
        response = self.client.post(self.url, {"query": "ML"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, {"query": "ML"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("research_ai.views.expert_finder_views.get_document_content")
    @patch("research_ai.views.expert_finder_views.run_expert_finder_search.delay")
    def test_create_with_document_returns_201(
        self, mock_delay, mock_get_document_content
    ):
        mock_get_document_content.return_value = ("abstract text", "abstract")
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Topic Paper",
            paper_publish_date="2021-06-01",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "unified_document_id": paper.unified_document_id,
                "input_type": "abstract",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn("search_id", data)
        search = ExpertSearch.objects.get(id=data["search_id"])
        self.assertEqual(search.created_by, self.moderator)
        mock_delay.assert_called_once()

    @patch("research_ai.views.expert_finder_views.get_document_content")
    @patch("research_ai.views.expert_finder_views.run_expert_finder_search.delay")
    def test_create_persists_additional_context_and_passes_to_task(
        self, mock_delay, mock_get_document_content
    ):
        mock_get_document_content.return_value = ("abstract text", "abstract")
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Ctx Paper",
            paper_publish_date="2021-06-01",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {
                "unified_document_id": paper.unified_document_id,
                "input_type": "abstract",
                "additional_context": "  Prefer experts in oncology.  ",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        search_id = response.json()["search_id"]
        search = ExpertSearch.objects.get(id=search_id)
        expected_ctx = "Prefer experts in oncology."
        self.assertEqual(search.additional_context, expected_ctx)
        mock_delay.assert_called_once()
        _, kwargs = mock_delay.call_args
        self.assertEqual(kwargs.get("additional_context"), expected_ctx)

    def test_create_without_required_fields_returns_400(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_unified_document_not_found_returns_404(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"unified_document_id": 999999, "input_type": "abstract"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


def _make_search(created_by, name="Manual Add Search"):
    return ExpertSearch.objects.create(
        created_by=created_by,
        name=name,
        query="ML",
        input_type=ExpertSearch.InputType.CUSTOM_QUERY,
        status=ExpertSearch.Status.COMPLETED,
        progress=100,
    )


class ExpertSearchAddExpertViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.search = _make_search(self.moderator)
        self.url = (
            f"/api/research_ai/expert-finder/searches/{self.search.id}/experts/"
        )

    def _payload(self, **overrides):
        payload = {
            "email": "alice@example.com",
            "first_name": "Alice",
            "last_name": "Test",
            "academic_title": "Professor",
            "affiliation": "MIT",
            "expertise": "ML",
        }
        payload.update(overrides)
        return payload

    def test_post_requires_authentication(self):
        response = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_requires_editor(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_404_for_unknown_search(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            "/api/research_ai/expert-finder/searches/999999/experts/",
            self._payload(),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_post_email_required(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(self.url, {"first_name": "Alice"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_creates_new_expert_and_search_expert(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(self.url, self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["email"], "alice@example.com")
        self.assertEqual(data["first_name"], "Alice")
        self.assertEqual(data["academic_title"], "Professor")

        expert = Expert.objects.get(email__iexact="alice@example.com")
        self.assertEqual(data["id"], expert.id)
        self.assertTrue(
            SearchExpert.objects.filter(
                expert_search=self.search, expert=expert
            ).exists()
        )

    def test_post_normalizes_email_to_lowercase(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            self._payload(email="Alice@Example.COM"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Expert.objects.filter(email="alice@example.com").exists()
        )

    def test_post_upserts_existing_expert_preserving_non_blank_fields(self):
        existing = Expert.objects.create(
            email="bob@example.com",
            first_name="Bob",
            last_name="Llmfound",
            academic_title="Associate Professor",
            affiliation="Stanford",
            expertise="NLP",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"email": "bob@example.com"},  # blank everywhere else
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Expert.objects.filter(email="bob@example.com").count(), 1)

        existing.refresh_from_db()
        self.assertEqual(existing.first_name, "Bob")
        self.assertEqual(existing.affiliation, "Stanford")

    def test_post_appends_manual_source_tag(self):
        existing = Expert.objects.create(
            email="carol@example.com",
            first_name="Carol",
            sources=[{"type": "llm", "model": "test"}],
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url, self._payload(email="carol@example.com"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        existing.refresh_from_db()
        self.assertEqual(len(existing.sources), 2)
        self.assertEqual(existing.sources[0]["type"], "llm")
        self.assertEqual(existing.sources[1]["type"], "manual")
        self.assertEqual(existing.sources[1]["added_by"], self.moderator.id)
        self.assertIn("added_at", existing.sources[1])

    def test_post_assigns_next_position(self):
        for i, email in enumerate(["x@e.com", "y@e.com", "z@e.com"]):
            ex = Expert.objects.create(email=email, first_name=email.split("@")[0])
            SearchExpert.objects.create(
                expert_search=self.search, expert=ex, position=i
            )

        self.client.force_authenticate(self.moderator)
        response = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_expert = Expert.objects.get(email="alice@example.com")
        link = SearchExpert.objects.get(
            expert_search=self.search, expert=new_expert
        )
        self.assertEqual(link.position, 3)

    def test_post_duplicate_in_same_search_returns_409(self):
        self.client.force_authenticate(self.moderator)
        first = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            SearchExpert.objects.filter(expert_search=self.search).count(), 1
        )
        self.assertEqual(
            Expert.objects.filter(email="alice@example.com").count(), 1
        )

    @patch("research_ai.views.email_views.generate_expert_email")
    def test_manual_expert_can_have_email_generated(self, mock_generate):
        mock_generate.return_value = ("Subject", "Body")
        self.client.force_authenticate(self.moderator)
        add_response = self.client.post(self.url, self._payload(), format="json")
        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)

        gen_response = self.client.post(
            "/api/research_ai/expert-finder/generate-email/",
            {
                "expert_search_id": self.search.id,
                "expert_email": "alice@example.com",
                "template": "collaboration",
            },
            format="json",
        )
        self.assertEqual(gen_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(GeneratedEmail.objects.count(), 1)
        rec = GeneratedEmail.objects.get()
        self.assertEqual(rec.expert_email, "alice@example.com")
        self.assertEqual(rec.expert_search_id, self.search.id)
