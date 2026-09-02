"""API tests for the proposal-draft endpoints.

The Celery task is patched at the view boundary; running the actual
drafting loop is covered by ``test_proposal_draft_service``.
"""

from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import Expert, ExpertSearch, ProposalDraft, SearchExpert
from user.tests.helpers import create_random_authenticated_user

BASE_URL = "/api/research_ai/expert-finder/proposal-drafts/"
MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}


@override_settings(**MODEL_SETTINGS)
class ProposalDraftCreateViewTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.expert = Expert.objects.create(email="jane@example.edu")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="protein folding",
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=self.expert,
        )

    @patch("research_ai.views.proposal_draft_views.run_proposal_draft_task.delay")
    def test_default_tier_user_cannot_create(self, mock_delay):
        # Arrange
        own_search = ExpertSearch.objects.create(
            created_by=self.user,
            query="protein folding",
        )
        own_search_expert = SearchExpert.objects.create(
            expert_search=own_search,
            expert=self.expert,
        )
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            BASE_URL, {"search_expert_id": own_search_expert.id}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_delay.assert_not_called()

    @patch("research_ai.views.proposal_draft_views.run_proposal_draft_task.delay")
    def test_create_returns_201_and_enqueues_task(self, mock_delay):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL, {"search_expert_id": self.search_expert.id}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        draft = ProposalDraft.objects.get(id=data["id"])
        self.assertEqual(draft.search_expert_id, self.search_expert.id)
        self.assertEqual(draft.created_by, self.moderator)
        self.assertEqual(draft.status, ProposalDraft.Status.PENDING)
        self.assertEqual(draft.step, ProposalDraft.Step.QUEUED)
        self.assertEqual(data["status"], ProposalDraft.Status.PENDING)
        mock_delay.assert_called_once_with(draft.id)

    @patch(
        "research_ai.views.proposal_draft_views.run_proposal_draft_task.delay",
        side_effect=RuntimeError("broker unavailable"),
    )
    def test_enqueue_failure_marks_draft_failed(self, _mock_delay):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL, {"search_expert_id": self.search_expert.id}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], "proposal_draft_enqueue_failed")
        draft = ProposalDraft.objects.get()
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)
        self.assertEqual(draft.error_message, "Could not queue proposal drafting task")

    @override_settings(
        ANTHROPIC_AWS_WORKSPACE_ID="ws-test", AWS_REGION_NAME="us-east-1"
    )
    @patch("research_ai.views.proposal_draft_views.run_proposal_draft_task.delay")
    def test_create_records_a_selected_model(self, mock_delay):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL,
            {
                "search_expert_id": self.search_expert.id,
                "model": "claude_platform:claude-sonnet-5",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        draft = ProposalDraft.objects.get(id=data["id"])
        self.assertEqual(draft.model_ref, "claude_platform:claude-sonnet-5")
        self.assertEqual(data["model_ref"], "claude_platform:claude-sonnet-5")
        mock_delay.assert_called_once_with(draft.id)

    @patch("research_ai.views.proposal_draft_views.run_proposal_draft_task.delay")
    def test_create_records_generation_options_for_the_worker(self, mock_delay):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL,
            {
                "search_expert_id": self.search_expert.id,
                "effort": "high",
                "thinking": "disabled",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        draft = ProposalDraft.objects.get(id=response.json()["id"])
        self.assertEqual(
            draft.run_config,
            {"effort": "high", "thinking": "disabled"},
        )
        mock_delay.assert_called_once_with(draft.id)

    @override_settings(
        ANTHROPIC_AWS_WORKSPACE_ID="ws-test", AWS_REGION_NAME="us-east-1"
    )
    @patch("research_ai.views.proposal_draft_views.run_proposal_draft_task.delay")
    def test_create_rejects_effort_for_haiku(self, mock_delay):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL,
            {
                "search_expert_id": self.search_expert.id,
                "model": "claude_platform:claude-haiku-4-5",
                "effort": "high",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not support effort", response.json()["detail"])
        self.assertFalse(ProposalDraft.objects.exists())
        mock_delay.assert_not_called()

    @patch("research_ai.views.proposal_draft_views.run_proposal_draft_task.delay")
    def test_create_with_unknown_model_returns_400(self, mock_delay):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL,
            {
                "search_expert_id": self.search_expert.id,
                "model": "openrouter:acme/not-a-model",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("model", response.json())
        self.assertFalse(ProposalDraft.objects.exists())
        mock_delay.assert_not_called()

    def test_create_without_search_expert_id_returns_400(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(BASE_URL, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_unknown_search_expert_returns_404(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL, {"search_expert_id": 999999}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("research_ai.views.proposal_draft_views.run_proposal_draft_task.delay")
    def test_create_with_active_draft_returns_409(self, mock_delay):
        # Arrange
        draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            status=ProposalDraft.Status.PROCESSING,
        )
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            BASE_URL, {"search_expert_id": self.search_expert.id}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(ProposalDraft.objects.count(), 1)
        mock_delay.assert_not_called()
        self.assertEqual(response.json()["proposal_draft_id"], draft.id)


@override_settings(**MODEL_SETTINGS)
class ProposalDraftDetailViewTests(APITestCase):
    def setUp(self):
        # Arrange
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.expert = Expert.objects.create(email="jane@example.edu")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="protein folding",
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=self.expert,
        )
        self.draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.moderator,
            status=ProposalDraft.Status.FAILED,
            step=ProposalDraft.Step.DRAFTING,
            rounds_used=2,
            error_message="gates not cleared within 2 rounds",
        )

    def test_default_tier_user_cannot_read_own_detail(self):
        # Arrange
        self.draft.created_by = self.user
        self.draft.save(update_fields=["created_by"])
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(f"{BASE_URL}{self.draft.id}/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_detail_returns_job_state(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(f"{BASE_URL}{self.draft.id}/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], self.draft.id)
        self.assertEqual(data["search_expert"], self.search_expert.id)
        self.assertEqual(data["status"], ProposalDraft.Status.FAILED)
        self.assertEqual(data["step"], ProposalDraft.Step.DRAFTING)
        self.assertEqual(data["rounds_used"], 2)
        self.assertEqual(data["error_message"], "gates not cleared within 2 rounds")
        self.assertIsNone(data["note"])

    def test_detail_not_found_returns_404(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(f"{BASE_URL}999999/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(**MODEL_SETTINGS)
class ProposalDraftCancelViewTests(APITestCase):
    def setUp(self):
        # Arrange
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        self.user = create_random_authenticated_user("user", moderator=False)
        self.expert = Expert.objects.create(email="jane@example.edu")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.moderator,
            query="protein folding",
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=self.expert,
        )
        self.draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.moderator,
            status=ProposalDraft.Status.PROCESSING,
            step=ProposalDraft.Step.JUDGING,
        )

    def _cancel(self, draft_id=None):
        return self.client.post(f"{BASE_URL}{draft_id or self.draft.id}/cancel/")

    def test_default_tier_user_cannot_cancel_own_draft(self):
        # Arrange
        self.draft.created_by = self.user
        self.draft.save(update_fields=["created_by"])
        self.client.force_authenticate(self.user)

        # Act
        response = self._cancel()

        # Assert
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, ProposalDraft.Status.PROCESSING)

    def test_cancel_requires_authentication(self):
        # Act
        response = self._cancel()

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cancel_stops_an_in_flight_draft(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self._cancel()

        # Assert: the draft comes back with the state the caller asked for, so a
        # client needs no follow-up poll to know where it landed.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["cancelled"])
        self.assertEqual(data["id"], self.draft.id)
        self.assertEqual(data["status"], ProposalDraft.Status.CANCELLED)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, ProposalDraft.Status.CANCELLED)

    def test_cancelling_a_finished_draft_leaves_it_alone(self):
        # Arrange: a draft that reached a terminal status on its own. Repeating a
        # cancel takes the same path, so this stands for both.
        self.client.force_authenticate(self.moderator)
        ProposalDraft.objects.filter(id=self.draft.id).update(
            status=ProposalDraft.Status.COMPLETED
        )

        # Act
        response = self._cancel()

        # Assert: idempotent -- a client that cannot tell whether its request
        # landed can simply send it again -- and the reply carries the status the
        # draft actually reached rather than assuming it was cancelled.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["cancelled"])
        self.assertEqual(response.json()["status"], ProposalDraft.Status.COMPLETED)

    def test_cancel_not_found_returns_404(self):
        # Arrange
        self.client.force_authenticate(self.moderator)

        # Act
        response = self._cancel(draft_id=999999)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
