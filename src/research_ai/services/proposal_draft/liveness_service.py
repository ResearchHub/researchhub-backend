"""Reclaiming proposal drafts whose worker stopped heartbeating."""

import logging

from django.db import transaction
from django.utils import timezone

from research_ai.models import AgentExecution, ProposalDraft
from research_ai.services.agent_persistence import AgentExecutionLivenessService
from research_ai.services.proposal_draft.cancel_service import ACTIVE_STATUSES

logger = logging.getLogger(__name__)

WORKER_LOST_MESSAGE = "The drafting worker stopped before the run finished."


class ProposalDraftLivenessService:
    """Fails queued or running drafts whose lease lapsed, freeing admission."""

    def __init__(
        self, *, execution_liveness_service: AgentExecutionLivenessService | None = None
    ):
        self.executions = (
            AgentExecutionLivenessService()
            if execution_liveness_service is None
            else execution_liveness_service
        )

    def reclaim_lost(self, *, user=None, now=None) -> list[ProposalDraft]:
        """Fail every active draft whose lease lapsed, optionally one user's."""
        current = now or timezone.now()
        candidates = ProposalDraft.objects.filter(
            status__in=ACTIVE_STATUSES,
            usage_reservation_expires_at__lt=current,
        )
        if user is not None:
            candidates = candidates.filter(created_by=user)
        reclaimed = []
        for draft in candidates.order_by("id"):
            try:
                if self._reclaim(draft, now=current):
                    reclaimed.append(draft)
            except Exception:  # noqa: BLE001 - one draft must not stop the sweep
                # Nothing was written for this draft; the next sweep retries it.
                logger.exception(
                    "could not reclaim a lost proposal draft",
                    extra={"draft_id": draft.id},
                )
        return reclaimed

    def _reclaim(self, draft: ProposalDraft, *, now) -> bool:
        # One transaction, trace first: a terminal draft whose trace still ran
        # would block admission with no lease left for any sweep to act on.
        with transaction.atomic():
            locked = (
                ProposalDraft.objects.select_for_update()
                .filter(
                    id=draft.id,
                    status__in=ACTIVE_STATUSES,
                    usage_reservation_expires_at__lt=now,
                )
                .first()
            )
            if locked is None:
                return False
            self._seal_execution(locked)
            ProposalDraft.objects.filter(id=locked.id).update(
                status=ProposalDraft.Status.FAILED,
                error_message=WORKER_LOST_MESSAGE,
                usage_reservation_expires_at=None,
                updated_date=now,
            )
        draft.refresh_from_db()
        logger.warning(
            "reclaimed a proposal draft whose worker was lost",
            extra={"draft_id": draft.id, "step": draft.step},
        )
        return True

    def _seal_execution(self, draft: ProposalDraft) -> None:
        """Seal the draft's active trace execution, if it has one."""
        conversation = draft.agent_conversation
        if conversation is None:
            return
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
            self.executions.seal_lost(execution)
