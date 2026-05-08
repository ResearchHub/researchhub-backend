# Expert finder API view tests
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import ExpertSearch
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
