"""Cancelling a queued or in-flight proposal-drafting job."""

from unittest.mock import patch

from django.test import TestCase

from note.tests.helpers import create_note
from research_ai.models import (
    AgentConversation,
    AgentExecution,
    Expert,
    ExpertSearch,
    ProposalDraft,
    SearchExpert,
)
from research_ai.services.agent_persistence import AgentExecutionService
from research_ai.services.proposal_draft.cancel_service import (
    ProposalDraftCancelledError,
    ProposalDraftCancelService,
)
from research_ai.services.proposal_draft.config import ProposalDraftConfig
from research_ai.services.proposal_draft.draft_recorder import DraftRecorder
from research_ai.services.proposal_draft.run_state import ProposalRunState
from research_ai.tasks import run_proposal_draft_task
from user.tests.helpers import create_random_default_user


class ProposalDraftCancelServiceTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("mod")
        self.expert = Expert.objects.create(email="jane@example.edu")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user, query="protein folding"
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search, expert=self.expert
        )
        self.cancels = ProposalDraftCancelService()

    def _draft(self, status=ProposalDraft.Status.PROCESSING, *, conversation=None):
        return ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.user,
            status=status,
            step=ProposalDraft.Step.JUDGING,
            agent_conversation=conversation,
        )

    def test_cancelling_a_running_draft_records_no_failure(self):
        # Arrange
        draft = self._draft()

        # Act
        cancelled = self.cancels.cancel(draft, cancelled_by=self.user)

        # Assert: a decision someone made, not a failure -- so the status
        # carries it and the error field stays empty. The step is left where the
        # run had got to.
        self.assertTrue(cancelled)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)
        self.assertEqual(draft.error_message, "")
        self.assertEqual(draft.step, ProposalDraft.Step.JUDGING)

    def test_cancelling_also_stops_the_traced_agent_execution(self):
        # Arrange: a run whose agent trace exists, so the loop has something to
        # notice -- it stops before its next tool call rather than at its next
        # write, which would come after the tool had run.
        conversation = AgentConversation.objects.create(workflow="proposal_draft")
        draft = self._draft(conversation=conversation)
        recorder = AgentExecutionService().start(
            conversation, provider="fake", model="fake-model-v1"
        )

        # Act
        self.cancels.cancel(draft, cancelled_by=self.user)

        # Assert
        execution = AgentExecution.objects.get(id=recorder.execution.id)
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)

    def test_cancelling_a_draft_with_no_trace_still_cancels_it(self):
        # Arrange: the agent trace is best-effort, so a run may have none. The
        # runner's own checkpoints read the draft, which is why this works.
        draft = self._draft(conversation=None)

        # Act
        cancelled = self.cancels.cancel(draft)

        # Assert
        self.assertTrue(cancelled)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)

    @patch("research_ai.tasks.run_proposal_draft")
    def test_cancelling_a_queued_draft_stops_the_task_from_running_it(self, mock_run):
        # Arrange: cancelled before any worker claimed it.
        draft = self._draft(status=ProposalDraft.Status.PENDING)
        self.cancels.cancel(draft)

        # Act: the task is delivered afterwards.
        result = run_proposal_draft_task(draft.id)

        # Assert: the claim is a conditional update on PENDING, so there is
        # nothing left to claim and no drafting work happens.
        mock_run.assert_not_called()
        self.assertEqual(result["skipped"], "already_claimed")
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)

    def test_cancelling_an_already_terminal_draft_reports_false(self):
        # Arrange: a draft that finished on its own. Cancelling one that is
        # already cancelled takes the same path -- neither is active.
        draft = self._draft(status=ProposalDraft.Status.COMPLETED)

        # Act
        cancelled = self.cancels.cancel(draft)

        # Assert: the ordinary race of stopping a job that already stopped, and
        # the outcome it reached is left as it was.
        self.assertFalse(cancelled)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)

    def test_a_cancelled_draft_refuses_its_runs_terminal_writes(self):
        # Arrange: the worker holds a stale draft instance from before the
        # cancel -- which is the normal case, since the cancel commits in another
        # process. Every write of its own that moves ``status`` must be refused,
        # or the run reverts a decision someone already made and the endpoint's
        # `cancelled: true` becomes a lie.
        draft = self._draft()
        state = ProposalRunState(ProposalDraftConfig(max_rounds=2))
        stale = ProposalDraft.objects.get(id=draft.id)
        recorder = DraftRecorder(stale, state)
        self.cancels.cancel(draft)
        note, _content = create_note(self.user, organization=None)

        # Act & Assert: completing is refused outright -- it is the write that
        # would publish -- and both of the other two decline to move the status.
        with self.assertRaises(ProposalDraftCancelledError):
            recorder.complete(note)
        with self.assertRaises(ProposalDraftCancelledError):
            recorder.mark_processing({"generator_model_id": "fake"})
        self.assertEqual(
            recorder.fail("gates not cleared")["status"],
            ProposalDraft.Status.CANCELLED,
        )
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)
        self.assertIsNone(draft.note)
        self.assertEqual(draft.error_message, "")

    def test_cancelling_frees_the_expert_for_a_fresh_draft(self):
        # Arrange: one active draft per search expert is enforced, so a job stuck
        # active would refuse every later attempt for that expert.
        draft = self._draft()

        # Act
        self.cancels.cancel(draft)

        # Assert
        replacement = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.user,
            status=ProposalDraft.Status.PENDING,
        )
        self.assertEqual(replacement.status, ProposalDraft.Status.PENDING)
        self.assertNotEqual(replacement.id, draft.id)
