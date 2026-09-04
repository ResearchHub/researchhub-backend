"""Tests for proposal-draft creation outside the HTTP boundary."""

from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase, override_settings
from django.utils import timezone

from research_ai.models import (
    AgentConversation,
    AgentExecution,
    Expert,
    ExpertSearch,
    ProposalDraft,
    SearchExpert,
)
from research_ai.services.proposal_draft.create_service import (
    ProposalDraftAlreadyActiveError,
    ProposalDraftCreateService,
    ProposalDraftEnqueueError,
)
from research_ai.services.usage_budget import UsageWorkInProgressError
from user.tests.helpers import create_random_authenticated_user

MODEL_SETTINGS = {
    "ANTHROPIC_AWS_WORKSPACE_ID": "ws-test",
    "AWS_REGION_NAME": "us-east-1",
    "OPENROUTER_API_KEY": "or-test",
}


@override_settings(**MODEL_SETTINGS)
class ProposalDraftCreateServiceTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("mod", moderator=True)
        self.expert = Expert.objects.create(email="jane@example.edu")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user,
            query="protein folding",
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=self.expert,
        )

    def test_create_applies_policy_persists_and_enqueues(self):
        # Arrange
        enqueue = Mock()
        service = ProposalDraftCreateService(enqueue=enqueue)

        # Act
        draft = service.create(
            search_expert=self.search_expert,
            created_by=self.user,
            effort="high",
            thinking="disabled",
        )

        # Assert
        self.assertEqual(draft.status, ProposalDraft.Status.PENDING)
        self.assertEqual(draft.step, ProposalDraft.Step.QUEUED)
        self.assertTrue(draft.model_ref)
        self.assertEqual(
            draft.run_config,
            {"effort": "high", "thinking": "disabled"},
        )
        self.assertIsNotNone(draft.usage_reservation_expires_at)
        enqueue.assert_called_once_with(draft.id)

    def test_create_persists_a_selected_model(self):
        # Arrange
        enqueue = Mock()

        # Act
        draft = ProposalDraftCreateService(enqueue=enqueue).create(
            search_expert=self.search_expert,
            created_by=self.user,
            model_ref="claude_platform:claude-sonnet-5",
        )

        # Assert
        self.assertEqual(draft.model_ref, "claude_platform:claude-sonnet-5")
        enqueue.assert_called_once_with(draft.id)

    def test_create_rejects_unsupported_generation_options(self):
        # Arrange
        enqueue = Mock()

        # Act / Assert
        with self.assertRaisesRegex(ValueError, "does not support effort"):
            ProposalDraftCreateService(enqueue=enqueue).create(
                search_expert=self.search_expert,
                created_by=self.user,
                model_ref="claude_platform:claude-haiku-4-5",
                effort="high",
            )
        self.assertFalse(ProposalDraft.objects.exists())
        enqueue.assert_not_called()

    def test_create_replaces_a_draft_whose_worker_was_lost(self):
        # Arrange: the expert's last draft is stuck PROCESSING with a lapsed lease.
        lost = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.user,
            status=ProposalDraft.Status.PROCESSING,
            usage_reservation_expires_at=timezone.now() - timedelta(seconds=1),
        )
        enqueue = Mock()

        # Act
        draft = ProposalDraftCreateService(enqueue=enqueue).create(
            search_expert=self.search_expert,
            created_by=self.user,
        )

        # Assert
        lost.refresh_from_db()
        self.assertEqual(lost.status, ProposalDraft.Status.FAILED)
        self.assertEqual(draft.status, ProposalDraft.Status.PENDING)
        enqueue.assert_called_once_with(draft.id)

    def test_create_replaces_a_chat_turn_whose_worker_was_lost(self):
        # Arrange: the user's notebook turn died mid-run; it, too, holds the
        # user's single budget slot.
        conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        lost = AgentExecution.objects.create(
            conversation=conversation,
            status=AgentExecution.Status.RUNNING,
            attempt=1,
            usage_reservation_expires_at=timezone.now() - timedelta(seconds=1),
        )
        enqueue = Mock()

        # Act
        draft = ProposalDraftCreateService(enqueue=enqueue).create(
            search_expert=self.search_expert,
            created_by=self.user,
        )

        # Assert
        lost.refresh_from_db()
        self.assertEqual(lost.status, AgentExecution.Status.FAILED)
        self.assertEqual(lost.stop_reason, "worker_lost")
        self.assertEqual(draft.status, ProposalDraft.Status.PENDING)
        enqueue.assert_called_once_with(draft.id)

    def test_create_rejects_an_expert_with_active_draft(self):
        # Arrange
        active = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.user,
            status=ProposalDraft.Status.PROCESSING,
        )
        enqueue = Mock()

        # Act / Assert
        with self.assertRaises(ProposalDraftAlreadyActiveError) as raised:
            ProposalDraftCreateService(enqueue=enqueue).create(
                search_expert=self.search_expert,
                created_by=self.user,
            )
        self.assertEqual(raised.exception.draft, active)
        enqueue.assert_not_called()

    def test_create_honors_existing_user_budget_reservation(self):
        # Arrange
        other_expert = Expert.objects.create(email="other@example.edu")
        other_search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=other_expert,
        )
        ProposalDraft.objects.create(
            search_expert=other_search_expert,
            created_by=self.user,
            status=ProposalDraft.Status.PENDING,
        )
        enqueue = Mock()

        # Act / Assert
        with self.assertRaises(UsageWorkInProgressError):
            ProposalDraftCreateService(enqueue=enqueue).create(
                search_expert=self.search_expert,
                created_by=self.user,
            )
        self.assertEqual(ProposalDraft.objects.count(), 1)
        enqueue.assert_not_called()

    def test_enqueue_failure_marks_draft_failed_and_releases_reservation(self):
        # Arrange
        enqueue = Mock(side_effect=RuntimeError("broker unavailable"))

        # Act / Assert
        with self.assertRaises(ProposalDraftEnqueueError):
            ProposalDraftCreateService(enqueue=enqueue).create(
                search_expert=self.search_expert,
                created_by=self.user,
            )
        draft = ProposalDraft.objects.get()
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)
        self.assertEqual(draft.error_message, "Could not queue proposal drafting task")
        self.assertIsNone(draft.usage_reservation_expires_at)
