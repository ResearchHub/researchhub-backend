"""Tests that hub editors (non-moderators) can access Research AI endpoints.

The recent change added ``UserIsEditor | IsModerator`` to all Research AI
views. Previously only moderators were allowed. These tests verify the
editor access path works correctly.
"""

from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import ExpertSearch
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class EditorAccessToExpertSearchTests(APITestCase):
    """Verify that hub editors can use expert-finder endpoints."""

    def setUp(self):
        self.editor, self.hub = create_hub_editor("editor_ai", "AI Hub")
        self.regular_user = create_random_authenticated_user("regular_ai")

    @patch("research_ai.tasks.process_expert_search_task.delay")
    def test_editor_can_create_expert_search(self, mock_delay):
        self.client.force_authenticate(self.editor)
        response = self.client.post(
            "/api/research_ai/expert-finder/search/",
            {"query": "Machine learning"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("search_id", response.json())

    def test_regular_user_cannot_create_expert_search(self):
        self.client.force_authenticate(self.regular_user)
        response = self.client.post(
            "/api/research_ai/expert-finder/search/",
            {"query": "ML"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_can_list_searches(self):
        ExpertSearch.objects.create(
            created_by=self.editor,
            query="Test query",
            status=ExpertSearch.Status.COMPLETED,
        )
        self.client.force_authenticate(self.editor)
        response = self.client.get("/api/research_ai/expert-finder/searches/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["total"], 1)

    def test_editor_can_get_own_search_detail(self):
        search = ExpertSearch.objects.create(
            created_by=self.editor,
            query="Detail query",
            status=ExpertSearch.Status.COMPLETED,
        )
        self.client.force_authenticate(self.editor)
        response = self.client.get(
            f"/api/research_ai/expert-finder/search/{search.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_access_work_endpoint(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(title="Editor Paper", paper_publish_date="2021-01-01")
        self.client.force_authenticate(self.editor)
        response = self.client.get(
            f"/api/research_ai/expert-finder/work/{paper.unified_document_id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_access_invited_experts_endpoint(self):
        from paper.tests.helpers import create_paper

        paper = create_paper(title="Editor Invited Paper", paper_publish_date="2021-01-01")
        self.client.force_authenticate(self.editor)
        response = self.client.get(
            f"/api/research_ai/expert-finder/documents/{paper.unified_document_id}/invited/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
