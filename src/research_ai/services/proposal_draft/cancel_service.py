"""Stopping a proposal-drafting run that is queued or in flight.

Drafting is headless: nobody is watching it the way a user watches a notebook
chat turn, so when a run goes wrong -- a bad RFP, a model looping, a job that
should never have been started -- the only remedy was to wait for it to finish
or die. This gives editors and moderators the same stop control the chat has.

Cancellation is cooperative, and deliberately so. Nothing here reaches into the
worker; it records the decision on the record and, if a trace execution exists,
on that row too. The run notices at its next checkpoint and unwinds through its
ordinary paths:

* **Queued.** The task claims a draft with a conditional update on ``PENDING``,
  so a task delivered after this skips: there is nothing left to claim.
* **Drafting.** The agent loop checks that it still owns its execution before
  every tool call, so it stops before a tool takes effect rather than at its
  next write, which would come after.
* **Between phases.** The runner checks the draft's own status around its long
  steps -- the profile build, the drafting loop, each gate round -- which is the
  path that still works when the trace execution was never created (it is
  best-effort, so drafting continues without it).

The status is terminal from the moment it is written, so a worker that is still
mid-provider-call cannot revive the row: every terminal write the run makes is
guarded on the status it expects to be replacing.
"""

import logging

from django.db import transaction

from research_ai.models import AgentExecution, ProposalDraft
from research_ai.services.agent_persistence import AgentLivenessService

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (ProposalDraft.Status.PENDING, ProposalDraft.Status.PROCESSING)


class ProposalDraftCancelledError(InterruptedError):
    """Raised inside a run whose draft was cancelled, to unwind it.

    An ``InterruptedError`` because that is what the agent core already treats
    as "stop the run" rather than "this step failed": a provider call re-raises
    it and ``Toolset.dispatch`` propagates it instead of handing it back to the
    model as a retryable tool error. A checkpoint inside the submit handler
    depends on that -- anything else would be answered by another round.
    """


class ProposalDraftCancelService:
    """Marks a draft cancelled and stops whatever is driving it."""

    def __init__(self, liveness_service: AgentLivenessService | None = None):
        self.liveness = liveness_service or AgentLivenessService()

    def cancel(self, draft: ProposalDraft, *, cancelled_by=None) -> bool:
        """Cancel ``draft``; report whether this call is what stopped it.

        ``False`` means it had already reached a terminal status -- cancelled a
        moment ago by someone else, or finished on its own while the request was
        in flight. That is an ordinary race rather than an error, so callers
        treat it as success and simply report the state they found.
        """
        with transaction.atomic():
            locked = (
                ProposalDraft.objects.select_for_update()
                .filter(id=draft.id, status__in=_ACTIVE_STATUSES)
                .first()
            )
            if locked is None:
                return False
            # No error_message: the status alone says what happened, and writing
            # a failure string for a deliberate stop is what CANCELLED exists to
            # avoid. ``step`` is left where the run got to, so the record still
            # shows how far it had gone.
            locked.status = ProposalDraft.Status.CANCELLED
            locked.save(update_fields=["status", "updated_date"])
        draft.refresh_from_db()
        self._cancel_execution(draft)
        logger.info(
            "proposal draft cancelled",
            extra={
                "draft_id": draft.id,
                "step": draft.step,
                "cancelled_by": getattr(cancelled_by, "id", None),
            },
        )
        return True

    def _cancel_execution(self, draft: ProposalDraft) -> None:
        """Stop the trace execution too, so a running loop unwinds promptly.

        Best-effort in every direction: the execution is optional (trace
        creation cannot break drafting, so a run may have none), and the draft
        status alone is enough for the runner's own checkpoints.
        """
        conversation = draft.agent_conversation
        if conversation is None:
            return
        try:
            execution = (
                conversation.executions.filter(
                    status__in=[
                        AgentExecution.Status.PENDING,
                        AgentExecution.Status.RUNNING,
                    ]
                )
                .order_by("-attempt")
                .first()
            )
            if execution is not None:
                self.liveness.cancel(execution)
        except Exception:  # noqa: BLE001 - the draft is already cancelled
            logger.warning(
                "could not cancel the proposal draft's agent execution",
                extra={"draft_id": draft.id},
                exc_info=True,
            )
