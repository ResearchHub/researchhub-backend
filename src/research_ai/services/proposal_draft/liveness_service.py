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
        return [
            draft
            for draft in candidates.order_by("id")
            if self._reclaim(draft, now=current)
        ]

    def _reclaim(self, draft: ProposalDraft, *, now) -> bool:
        # Conditional on the lease still being lapsed, like every other write
        # that moves a draft's status: a slow worker may have renewed since the scan.
        with transaction.atomic():
            updated = ProposalDraft.objects.filter(
                id=draft.id,
                status__in=ACTIVE_STATUSES,
                usage_reservation_expires_at__lt=now,
            ).update(
                status=ProposalDraft.Status.FAILED,
                error_message=WORKER_LOST_MESSAGE,
                usage_reservation_expires_at=None,
                updated_date=now,
            )
        if not updated:
            return False
        draft.refresh_from_db()
        self._seal_execution(draft)
        logger.warning(
            "reclaimed a proposal draft whose worker was lost",
            extra={"draft_id": draft.id, "step": draft.step},
        )
        return True

    def _seal_execution(self, draft: ProposalDraft) -> None:
        """Seal the trace execution too; best-effort, as its creation was."""
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
                self.executions.seal_lost(execution)
        except Exception:  # noqa: BLE001 - the draft is already failed
            logger.warning(
                "could not seal the lost proposal draft's agent execution",
                extra={"draft_id": draft.id},
                exc_info=True,
            )
