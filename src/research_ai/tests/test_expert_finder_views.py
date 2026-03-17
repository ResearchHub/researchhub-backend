# Expert finder API view tests
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import ExpertSearch
from user.tests.helpers import create_hub_editor, create_random_authenticated_user

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
            self.url,
            {"query": "Machine learning"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn("search_id", data)
        search = ExpertSearch.objects.get(id=data["search_id"])
        self.assertEqual(search.created_by, self.moderator)
        mock_delay.assert_called_once()

    def test_create_without_query_returns_400(self):
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

    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_editor_can_create_search(self, mock_delay):
        """Hub editors (non-moderators) should have access after the
        IsModerator -> UserIsEditor | IsModerator permission change."""
        editor, _hub = create_hub_editor("expert_ed", "expert_hub")
        self.client.force_authenticate(editor)
        response = self.client.post(
            self.url, {"query": "Machine learning"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        search = ExpertSearch.objects.get(id=response.json()["search_id"])
        self.assertEqual(search.created_by, editor)
        mock_delay.assert_called_once()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ExpertSearchListViewEditorTests(APITestCase):
    """Verify hub editors can list their own expert searches."""

    def setUp(self):
        self.editor, _hub = create_hub_editor("list_ed", "list_hub")
        self.url = "/api/research_ai/expert-finder/searches/"
        ExpertSearch.objects.create(
            created_by=self.editor,
            name="Editor Search",
            query="NLP",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
            status=ExpertSearch.Status.COMPLETED,
            progress=100,
            expert_results=[],
        )

    def test_editor_can_list_own_searches(self):
        self.client.force_authenticate(self.editor)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["total"], 1)
