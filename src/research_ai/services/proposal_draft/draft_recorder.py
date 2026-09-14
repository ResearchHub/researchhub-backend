"""All ``ProposalDraft`` record writes and progress emission for one run.

The runner decides what happened; the recorder owns how that lands on the
record and reaches the caller's progress callback. It reads the shared
``ProposalRunState`` rather than taking loose values, so the per-round and
terminal writes cannot drift apart from the state the run actually reached.

Every write that moves ``status`` is a conditional update on the status it
expects to be replacing, never a save from this run's in-memory instance. The
cancelling request runs in another process and holds its row lock only until it
commits, so by the time this run writes, its own copy of the draft may be stale
by a decision someone already made. An unguarded save would revive a cancelled
draft -- and for ``complete`` that means publishing a Note for a run that was
called off, which is why the Note is written inside the same transaction as the
guard and rolls back with it.

Writes that carry no status -- ``set_step``, ``persist_round`` -- stay
unconditional. They record how far the run got, which remains true of a
cancelled run, and they cannot resurrect it.
"""

import logging

from django.utils import timezone

from research_ai.models import ProposalDraft
from research_ai.services.proposal_draft.cancel_service import (
    ACTIVE_STATUSES,
    ProposalDraftCancelledError,
)
from research_ai.services.proposal_draft.run_state import ProposalRunState

logger = logging.getLogger(__name__)


class DraftRecorder:
    """Persists one run's state onto its ``ProposalDraft`` record."""

    def __init__(
        self,
        draft: ProposalDraft,
        state: ProposalRunState,
        *,
        progress_callback=None,
    ):
        self.draft = draft
        self.state = state
        self.progress_callback = progress_callback

    def _claim(self, **fields) -> bool:
        """Write ``fields`` if the draft is still active; report whether it was.

        ``False`` means the draft reached a terminal status between this run's
        last checkpoint and this write -- in practice, someone cancelled it. The
        condition is "still active" rather than a single expected status because
        a run reaches its first write from ``PENDING`` when invoked directly and
        from ``PROCESSING`` when a task claimed it first.
        """
        updated = ProposalDraft.objects.filter(
            id=self.draft.id, status__in=ACTIVE_STATUSES
        ).update(updated_date=timezone.now(), **fields)
        if not updated:
            return False
        self.draft.refresh_from_db()
        return True

    def mark_processing(self, run_config: dict) -> None:
        # A task may have claimed the row PENDING -> PROCESSING already; either
        # way this must not write PROCESSING back over a cancellation that
        # landed in between.
        if not self._claim(
            status=ProposalDraft.Status.PROCESSING, run_config=run_config
        ):
            raise ProposalDraftCancelledError(
                f"proposal draft {self.draft.id} was cancelled before it started"
            )

    # -- progress ---------------------------------------------------------

    def set_step(self, step: str) -> None:
        if self.draft.step != step:
            self.draft.step = step
            self.draft.save(update_fields=["step", "updated_date"])
        self.emit_progress(step)

    def emit_progress(self, step: str) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(
                {
                    "step": step,
                    "status": self.draft.status,
                    "rounds_used": self.state.rounds_used,
                }
            )
        except Exception:  # noqa: BLE001 - progress must not break the run
            logger.debug("proposal draft progress callback failed", exc_info=True)

    # -- per-round write ----------------------------------------------------

    def persist_round(self) -> None:
        """Write this round's outcome to the record as soon as the gates run.

        Terminal ``complete``/``fail`` still write the authoritative final
        state, but persisting per round means an in-flight run -- or one that
        hangs or dies mid-loop before reaching a terminal path -- is inspectable
        with the latest submission, scores, and gate report rather than the
        zeroed defaults.
        """
        self.draft.rounds_used = self.state.rounds_used
        self.draft.final_scores = self.state.final_scores
        self.draft.gate_report = self.state.last_gate_report
        self.draft.last_submission = self.state.submitted or {}
        self.draft.save(
            update_fields=[
                "rounds_used",
                "final_scores",
                "gate_report",
                "last_submission",
                "updated_date",
            ]
        )

    # -- terminal writes ------------------------------------------------------

    def complete(self, note) -> dict:
        # The shipped draft is the best-scoring ACCEPTED round, which the loop
        # may have moved past -- persist that round's scores/report/submission so
        # the record matches the Note, not a later round that regressed.
        submission, gate_report, scores = self.state.accepted_outcome()
        # Raising here rolls the caller's transaction back, and the Note it
        # wrote goes with it: a cancelled run must not leave a published
        # proposal behind, so the publication and this guard succeed or fail
        # together.
        if not self._claim(
            note=note,
            final_scores=scores,
            gate_report=gate_report,
            last_submission=submission,
            rounds_used=self.state.rounds_used,
            status=ProposalDraft.Status.COMPLETED,
            step=ProposalDraft.Step.DONE,
            completed_at=timezone.now(),
            usage_reservation_expires_at=None,
        ):
            raise ProposalDraftCancelledError(
                f"proposal draft {self.draft.id} was cancelled before it shipped"
            )
        self.emit_progress(ProposalDraft.Step.DONE)
        return {
            "status": ProposalDraft.Status.COMPLETED,
            "proposal_draft_id": self.draft.id,
            "note_id": note.id,
            "rounds_used": self.state.rounds_used,
            "final_scores": scores,
            "gate_report": gate_report,
        }

    def fail(self, message: str) -> dict:
        # A cancelled run reaches here too: cancellation surfaces inside the run
        # as an ordinary error (an interrupted write, a refused tool call), and
        # every one of those paths ends in ``fail``. Checking the record is what
        # keeps a decision someone made from being written up as a failure --
        # and it belongs here rather than at each raise site, because there are
        # several and any future one would have to remember.
        if self.cancelled():
            return self.cancelled_result()
        # Persist the rejected draft so a failed run is still inspectable: a
        # FAILED run never writes a Note, so this is the only place its content
        # survives. The state picks the best-scoring round over the last one.
        submission, gate_report, scores = self.state.persisted_outcome()
        if not self._claim(
            rounds_used=self.state.rounds_used,
            last_submission=submission,
            gate_report=gate_report,
            final_scores=scores,
            status=ProposalDraft.Status.FAILED,
            error_message=message,
            usage_reservation_expires_at=None,
        ):
            # Cancelled in the gap between the check above and this write. The
            # decision wins over the failure it interrupted.
            return self.cancelled_result()
        return {
            "status": ProposalDraft.Status.FAILED,
            "proposal_draft_id": self.draft.id,
            "rounds_used": self.state.rounds_used,
            "gate_report": self.draft.gate_report,
            "last_submission": self.draft.last_submission,
            "error_message": message,
        }

    # -- cancellation ---------------------------------------------------------

    def cancelled(self) -> bool:
        """Whether someone cancelled this draft, read fresh from the record.

        The cancelling request runs in another process, so the in-memory draft
        cannot be trusted for this -- an instance loaded before the cancel
        landed still reports the status it was created with.
        """
        return (
            ProposalDraft.objects.filter(
                id=self.draft.id, status=ProposalDraft.Status.CANCELLED
            )
            .only("id")
            .exists()
        )

    def cancelled_result(self) -> dict:
        """Persist how far a cancelled run got, and report it.

        The status is already written -- the cancelling request owns that -- so
        this only saves the work in hand. A cancelled run never writes a Note,
        so as with a failure this is the only place its draft survives.
        """
        self.persist_round()
        # Cancellation made the lifecycle terminal immediately, but a running
        # job kept its budget lease. This method is reached by that worker only
        # after its current provider call has returned and it has unwound.
        ProposalDraft.objects.filter(id=self.draft.id).update(
            usage_reservation_expires_at=None
        )
        self.draft.refresh_from_db()
        return {
            "status": ProposalDraft.Status.CANCELLED,
            "proposal_draft_id": self.draft.id,
            "rounds_used": self.state.rounds_used,
            "gate_report": self.draft.gate_report,
            "last_submission": self.draft.last_submission,
        }
