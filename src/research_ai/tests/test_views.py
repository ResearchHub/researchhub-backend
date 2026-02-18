from unittest.mock import patch
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from research_ai.models import ExpertSearch
from user.tests.helpers import create_random_authenticated_user


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ExpertSearchCreateViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.url = "/api/research_ai/expert-finder/search/"

    def test_create_requires_authentication(self):
        response = self.client.post(self.url, {"query": "ML"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_requires_moderator(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, {"query": "ML"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_create_with_query_returns_201(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url, {"query": "Machine learning"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn("search_id", data)
        search = ExpertSearch.objects.get(id=data["search_id"])
        self.assertEqual(search.created_by, self.moderator)
        mock_delay.assert_called_once()

    @patch("research_ai.views.expert_finder_views.get_document_content")
    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_create_with_unified_document_autofills_name(
        self, mock_delay, mock_get_document_content
    ):
        mock_get_document_content.return_value = ("abstract text", "abstract")
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Autofill Name Paper",
            paper_publish_date="2021-06-01",
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"unified_document_id": paper.unified_document_id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        search = ExpertSearch.objects.get(id=response.json()["search_id"])
        self.assertEqual(search.name, "Autofill Name Paper")

    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_create_with_name_uses_provided_name(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url,
            {"query": "Custom query", "name": "My custom search name"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        search = ExpertSearch.objects.get(id=response.json()["search_id"])
        self.assertEqual(search.name, "My custom search name")

    def test_create_without_query_returns_400(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_unified_document_not_found_returns_404(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            self.url, {"unified_document_id": 999999}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ExpertSearchDetailViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod2", moderator=True)
        self.other = create_random_authenticated_user("other", moderator=True)
        self.search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Detail test",
            status=ExpertSearch.Status.COMPLETED,
            expert_count=2,
        )
        self.url = "/api/research_ai/expert-finder/search/{}/".format(
            self.search.id
        )

    def test_get_own_search_returns_200(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["search_id"], self.search.id)

    def test_get_detail_returns_work_when_unified_document(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(
            title="Detail Work Paper",
            paper_publish_date="2020-01-01",
        )
        search = ExpertSearch.objects.create(
            created_by=self.moderator,
            unified_document=paper.unified_document,
            query="From paper",
            status=ExpertSearch.Status.COMPLETED,
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/search/{}/".format(search.id)
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("work", data)
        self.assertIsNotNone(data["work"])
        self.assertEqual(data["work"]["type"], "paper")
        self.assertEqual(data["work"]["id"], paper.id)
        self.assertIn("Detail Work Paper", data["work"]["title"])

    def test_get_other_user_search_returns_404(self):
        self.client.force_authenticate(self.other)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_invalid_search_id_returns_400(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(
            "/api/research_ai/expert-finder/search/abc/"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ExpertSearchListViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod3", moderator=True)
        self.url = "/api/research_ai/expert-finder/searches/"

    def test_list_returns_own_searches(self):
        ExpertSearch.objects.create(
            created_by=self.moderator,
            query="First",
            status=ExpertSearch.Status.COMPLETED,
        )
        ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Second",
            status=ExpertSearch.Status.PENDING,
        )
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["searches"]), 2)


class ExpertSearchProgressStreamViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod4", moderator=True)
        self.search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="Stream test",
            status=ExpertSearch.Status.PENDING,
        )
        self.url = "/api/research_ai/expert-finder/progress/{}/".format(
            self.search.id
        )

    def test_progress_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_progress_returns_sse_stream(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/event-stream", response.get("Content-Type", ""))
