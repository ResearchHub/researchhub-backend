"""Cancelling a queued or in-flight proposal-drafting job."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

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
from research_ai.services.usage_budget import atomic_turn_admission
from research_ai.services.usage_budget.reservation import reservation_deadline
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

    def test_running_cancellation_releases_concurrency_reservation(self):
        # Arrange
        draft = self._draft()
        draft.usage_reservation_expires_at = reservation_deadline()
        draft.save(update_fields=["usage_reservation_expires_at"])
        state = ProposalRunState(ProposalDraftConfig(max_rounds=2))
        recorder = DraftRecorder(draft, state)

        # Act: cancellation lands while provider work is still in flight.
        self.cancels.cancel(draft)

        # Assert: its provider attempts are accounted separately, so this lock goes.
        draft.refresh_from_db()
        self.assertIsNone(draft.usage_reservation_expires_at)
        recorder.cancelled_result()
        draft.refresh_from_db()
        self.assertIsNone(draft.usage_reservation_expires_at)

    def test_queued_cancellation_releases_budget_immediately(self):
        # Arrange
        draft = self._draft(status=ProposalDraft.Status.PENDING)
        draft.usage_reservation_expires_at = reservation_deadline()
        draft.save(update_fields=["usage_reservation_expires_at"])

        # Act
        self.cancels.cancel(draft)

        # Assert
        draft.refresh_from_db()
        self.assertIsNone(draft.usage_reservation_expires_at)

    def test_cancelling_running_draft_and_trace_releases_reservations(self):
        # Arrange: both reservations still have two hours remaining.
        conversation = AgentConversation.objects.create(
            user=self.user, workflow="proposal_draft"
        )
        draft = self._draft(conversation=conversation)
        expires_at = timezone.now() + timedelta(hours=2)
        draft.usage_reservation_expires_at = expires_at
        draft.save(update_fields=["usage_reservation_expires_at"])
        execution = AgentExecution.objects.create(
            conversation=conversation,
            attempt=1,
            status=AgentExecution.Status.RUNNING,
            usage_reservation_expires_at=expires_at,
        )

        # Act
        self.cancels.cancel(draft)

        # Assert: neither lifecycle reservation blocks another task.
        draft.refresh_from_db()
        execution.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)
        self.assertEqual(execution.status, AgentExecution.Status.CANCELLED)
        self.assertIsNone(draft.usage_reservation_expires_at)
        self.assertIsNone(execution.usage_reservation_expires_at)
        with atomic_turn_admission(self.user):
            pass

    def test_old_cancelled_draft_reservation_does_not_block_admission(self):
        # Arrange: an earlier deployment left a cancelled draft lease behind.
        draft = self._draft(status=ProposalDraft.Status.CANCELLED)
        draft.usage_reservation_expires_at = reservation_deadline()
        draft.save(update_fields=["usage_reservation_expires_at"])

        # Act / Assert
        with atomic_turn_admission(self.user):
            pass

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

    @patch("research_ai.tasks.run_proposal_draft")
    def test_a_crash_outside_the_runner_cannot_report_a_stop_as_a_failure(
        self, mock_run
    ):
        # Arrange: the draft was claimed and then cancelled, and the run raises
        # somewhere the runner's own handling does not cover -- constructing it,
        # or while persisting its cancelled outcome -- so the exception reaches
        # the task's last-resort handler.
        draft = self._draft(status=ProposalDraft.Status.PENDING)

        def _cancel_then_crash(*_args, **_kwargs):
            self.cancels.cancel(ProposalDraft.objects.get(id=draft.id))
            raise RuntimeError("lost the database")

        mock_run.side_effect = _cancel_then_crash

        # Act
        with self.assertRaises(RuntimeError):
            run_proposal_draft_task(draft.id)

        # Assert: that handler is conditional on the draft still being active,
        # like every write the runner makes. Unguarded it would overwrite a
        # deliberate stop with FAILED and stamp a crash message on it, so the
        # endpoint's `cancelled: true` would be contradicted by what the row
        # ends up showing.
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.CANCELLED)
        self.assertEqual(draft.error_message, "")

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

    def test_cancelling_again_sweeps_a_trace_the_first_cancel_could_not_see(self):
        # Arrange: the run created its execution just after the cancel looked for
        # one, so the first request left it RUNNING. Nothing else clears that
        # now -- the liveness sweep is gone, and the draft is already terminal --
        # so the retry has to do more than report the status back.
        conversation = AgentConversation.objects.create(workflow="proposal_draft")
        draft = self._draft(conversation=conversation)
        self.cancels.cancel(draft)
        late = AgentExecutionService().start(
            conversation, provider="fake", model="fake-model-v1"
        )

        # Act
        again = self.cancels.cancel(draft)

        # Assert: still reports it did not stop the draft -- it was already
        # stopped -- but the stranded execution is no longer RUNNING.
        self.assertFalse(again)
        self.assertEqual(
            AgentExecution.objects.get(id=late.execution.id).status,
            AgentExecution.Status.CANCELLED,
        )

    def test_cancelling_a_completed_draft_leaves_it_and_its_trace_alone(self):
        # Arrange: a draft that finished on its own, its execution still being
        # finalized. Cancelling one that is already cancelled takes the same
        # path -- neither is active.
        conversation = AgentConversation.objects.create(workflow="proposal_draft")
        draft = self._draft(
            status=ProposalDraft.Status.COMPLETED, conversation=conversation
        )
        recorder = AgentExecutionService().start(
            conversation, provider="fake", model="fake-model-v1"
        )

        # Act
        cancelled = self.cancels.cancel(draft)

        # Assert: the ordinary race of stopping a job that already stopped. The
        # outcome it reached is left as it was, and the sweep above must not
        # reach its trace either: that execution belongs to the outcome, and
        # cancelling one the run is still finalizing would record a cancellation
        # over a success.
        self.assertFalse(cancelled)
        draft.refresh_from_db()
        self.assertEqual(draft.status, ProposalDraft.Status.COMPLETED)
        self.assertEqual(
            AgentExecution.objects.get(id=recorder.execution.id).status,
            AgentExecution.Status.RUNNING,
        )

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
