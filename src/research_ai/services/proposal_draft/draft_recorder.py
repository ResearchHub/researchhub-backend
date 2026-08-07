"""All ``ProposalDraft`` record writes and progress emission for one run.

The runner decides what happened; the recorder owns how that lands on the
record and reaches the caller's progress callback. It reads the shared
``ProposalRunState`` rather than taking loose values, so the per-round and
terminal writes cannot drift apart from the state the run actually reached.
"""

import logging

from django.utils import timezone

from research_ai.models import ProposalDraft
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

    def mark_processing(self, run_config: dict) -> None:
        self.draft.status = ProposalDraft.Status.PROCESSING
        self.draft.run_config = run_config
        self.draft.save(update_fields=["status", "run_config", "updated_date"])

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
        self.draft.note = note
        self.draft.final_scores = scores
        self.draft.gate_report = gate_report
        self.draft.last_submission = submission
        self.draft.rounds_used = self.state.rounds_used
        self.draft.status = ProposalDraft.Status.COMPLETED
        self.draft.step = ProposalDraft.Step.DONE
        self.draft.completed_at = timezone.now()
        self.draft.save()
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
        self.draft.rounds_used = self.state.rounds_used
        self.draft.last_submission = submission
        self.draft.gate_report = gate_report
        self.draft.final_scores = scores
        self.draft.status = ProposalDraft.Status.FAILED
        self.draft.error_message = message
        self.draft.save()
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
        self.draft.refresh_from_db()
        return {
            "status": ProposalDraft.Status.CANCELLED,
            "proposal_draft_id": self.draft.id,
            "rounds_used": self.state.rounds_used,
            "gate_report": self.draft.gate_report,
            "last_submission": self.draft.last_submission,
        }
