"""Reclaiming proposal drafts whose worker stopped heartbeating."""

from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from research_ai.models import (
    AgentConversation,
    AgentExecution,
    Expert,
    ExpertSearch,
    ProposalDraft,
    SearchExpert,
)
from research_ai.services.agent_persistence import AgentExecutionService
from research_ai.services.proposal_draft.liveness_service import (
    WORKER_LOST_MESSAGE,
    ProposalDraftLivenessService,
)
from research_ai.services.usage_budget import (
    UsageWorkInProgressError,
    atomic_turn_admission,
)
from user.tests.helpers import create_random_default_user


class ProposalDraftLivenessTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("draft-liveness")
        self.expert = Expert.objects.create(email="jane@example.edu")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user, query="protein folding"
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search, expert=self.expert
        )
        self.liveness = ProposalDraftLivenessService()
        self.lapsed = timezone.now() - timedelta(seconds=1)
        self.live = timezone.now() + timedelta(minutes=1)

    def _draft(
        self,
        *,
        lease,
        status=ProposalDraft.Status.PROCESSING,
        conversation=None,
        created_by=None,
        search_expert=None,
    ):
        return ProposalDraft.objects.create(
            search_expert=search_expert or self.search_expert,
            created_by=created_by or self.user,
            status=status,
            step=ProposalDraft.Step.JUDGING,
            agent_conversation=conversation,
            usage_reservation_expires_at=lease,
        )

    def test_a_running_draft_whose_lease_lapsed_is_failed(self):
        # Arrange
        draft = self._draft(lease=self.lapsed)

        # Act
        reclaimed = self.liveness.reclaim_lost()

        # Assert
        self.assertEqual([item.id for item in reclaimed], [draft.id])
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)
        self.assertEqual(draft.error_message, WORKER_LOST_MESSAGE)
        self.assertIsNone(draft.usage_reservation_expires_at)
        self.assertEqual(draft.step, ProposalDraft.Step.JUDGING)

    def test_a_draft_with_a_live_lease_is_left_alone(self):
        # Arrange
        draft = self._draft(lease=self.live)

        # Act
        reclaimed = self.liveness.reclaim_lost()

        # Assert
        self.assertEqual(reclaimed, [])
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.PROCESSING)

    def test_a_queued_draft_past_its_claim_deadline_is_failed(self):
        # Arrange
        draft = self._draft(lease=self.lapsed, status=ProposalDraft.Status.PENDING)

        # Act
        self.liveness.reclaim_lost()

        # Assert
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)

    def test_reclaiming_also_seals_the_traced_agent_execution(self):
        # Arrange
        conversation = AgentConversation.objects.create(workflow="proposal_draft")
        draft = self._draft(lease=self.lapsed, conversation=conversation)
        recorder = AgentExecutionService().start(
            conversation, provider="fake", model="fake-model-v1"
        )

        # Act
        self.liveness.reclaim_lost()

        # Assert
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.stop_reason, "worker_lost")
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)

    def test_a_draft_whose_trace_cannot_be_sealed_waits_for_the_next_sweep(self):
        # Arrange: releasing the draft while its trace stayed RUNNING would block
        # admission for good, since the trace holds no lease of its own.
        conversation = AgentConversation.objects.create(workflow="proposal_draft")
        draft = self._draft(lease=self.lapsed, conversation=conversation)
        recorder = AgentExecutionService().start(
            conversation, provider="fake", model="fake-model-v1"
        )
        liveness = ProposalDraftLivenessService(
            execution_liveness_service=Mock(
                seal_lost=Mock(side_effect=RuntimeError("database unavailable"))
            )
        )

        # Act
        reclaimed = liveness.reclaim_lost()

        # Assert: nothing landed for this draft, so the lapsed lease still
        # selects it next time.
        self.assertEqual(reclaimed, [])
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.PROCESSING)
        self.assertEqual(draft.usage_reservation_expires_at, self.lapsed)
        recorder.execution.refresh_from_db()
        self.assertEqual(recorder.execution.status, AgentExecution.Status.RUNNING)

    def test_reclaiming_can_be_scoped_to_one_user(self):
        # Arrange
        other_user = create_random_default_user("draft-liveness-other")
        other_search = SearchExpert.objects.create(
            expert_search=ExpertSearch.objects.create(
                created_by=other_user, query="enzymes"
            ),
            expert=self.expert,
        )
        mine = self._draft(lease=self.lapsed)
        theirs = self._draft(
            lease=self.lapsed, created_by=other_user, search_expert=other_search
        )

        # Act
        reclaimed = self.liveness.reclaim_lost(user=self.user)

        # Assert
        self.assertEqual([item.id for item in reclaimed], [mine.id])
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, ProposalDraft.Status.PROCESSING)

    def test_a_reclaimed_draft_frees_admission(self):
        # Arrange
        self._draft(lease=self.lapsed)
        with (
            self.assertRaises(UsageWorkInProgressError),
            atomic_turn_admission(self.user),
        ):
            pass

        # Act
        self.liveness.reclaim_lost(user=self.user)

        # Assert
        with atomic_turn_admission(self.user):
            pass
