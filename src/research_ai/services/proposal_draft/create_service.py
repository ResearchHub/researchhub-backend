"""Create and enqueue budget-admitted proposal-draft jobs."""

import logging
from collections.abc import Callable

from django.db import IntegrityError

from research_ai.models import ProposalDraft, SearchExpert
from research_ai.services.agent import split_model_ref
from research_ai.services.agent.model_capabilities import validate_generation_options
from research_ai.services.proposal_draft.liveness_service import (
    ProposalDraftLivenessService,
)
from research_ai.services.usage_budget import (
    atomic_turn_admission,
    effective_generation_options,
    resolve_ai_tier,
    resolve_default_model,
)
from research_ai.services.usage_budget.reservation import claim_deadline

logger = logging.getLogger(__name__)


class ProposalDraftAlreadyActiveError(RuntimeError):
    """Raised when an expert already has a queued or running draft."""

    def __init__(self, draft: ProposalDraft):
        super().__init__("A proposal draft is already in progress for this expert")
        self.draft = draft


class ProposalDraftEnqueueError(RuntimeError):
    """Raised after a broker failure has transitioned the new draft to failed."""

    code = "proposal_draft_enqueue_failed"


def _enqueue_proposal_draft(draft_id: int) -> None:
    # Import lazily because tasks imports the proposal-draft runner package.
    from research_ai.tasks import run_proposal_draft_task

    run_proposal_draft_task.delay(draft_id)


class ProposalDraftCreateService:
    """Apply policy, reserve budget, persist, and enqueue one proposal draft."""

    def __init__(
        self,
        enqueue: Callable[[int], None] | None = None,
        *,
        liveness_service: ProposalDraftLivenessService | None = None,
    ):
        self.enqueue = enqueue if enqueue is not None else _enqueue_proposal_draft
        self.liveness = (
            ProposalDraftLivenessService()
            if liveness_service is None
            else liveness_service
        )

    def create(
        self,
        *,
        search_expert: SearchExpert,
        created_by,
        model_ref: str | None = None,
        effort: str | None = None,
        thinking: str | None = None,
        temperature: float | None = None,
    ) -> ProposalDraft:
        """Create and enqueue a draft, or raise a domain/admission exception."""
        # A draft whose worker died would otherwise hold both checks below.
        self.liveness.reclaim_lost(user=created_by)
        active = self._active_draft_for(search_expert)
        if active is not None:
            raise ProposalDraftAlreadyActiveError(active)

        policy = resolve_ai_tier(created_by)
        effective_model_ref = model_ref or resolve_default_model(policy)
        effort, thinking = effective_generation_options(
            policy,
            effort=effort,
            thinking=thinking,
        )
        provider_name, model_id = split_model_ref(effective_model_ref)
        validate_generation_options(
            provider_name,
            model_id or "",
            effort=effort,
            thinking=thinking,
            temperature=temperature,
        )

        run_config = {}
        if temperature is not None:
            run_config["temperature"] = temperature
        if effort is not None:
            run_config["effort"] = effort
        if thinking is not None:
            run_config["thinking"] = thinking

        try:
            with atomic_turn_admission(
                created_by,
                effective_model_ref,
                effort=effort,
                thinking=thinking,
            ):
                draft = ProposalDraft.objects.create(
                    search_expert=search_expert,
                    created_by=created_by,
                    status=ProposalDraft.Status.PENDING,
                    step=ProposalDraft.Step.QUEUED,
                    model_ref=effective_model_ref,
                    run_config=run_config,
                    # Held until a worker claims the job and takes over renewal.
                    usage_reservation_expires_at=claim_deadline(),
                )
        except IntegrityError:
            active = self._active_draft_for(search_expert)
            if active is not None:
                raise ProposalDraftAlreadyActiveError(active) from None
            raise

        try:
            self.enqueue(draft.id)
        except Exception as error:  # noqa: BLE001 - broker clients vary
            logger.exception("could not queue proposal draft %s", draft.id)
            ProposalDraft.objects.filter(
                id=draft.id,
                status=ProposalDraft.Status.PENDING,
            ).update(
                status=ProposalDraft.Status.FAILED,
                error_message="Could not queue proposal drafting task",
                usage_reservation_expires_at=None,
            )
            raise ProposalDraftEnqueueError(
                "Could not queue proposal drafting task"
            ) from error

        return draft

    @staticmethod
    def _active_draft_for(search_expert: SearchExpert) -> ProposalDraft | None:
        return ProposalDraft.objects.filter(
            search_expert=search_expert,
            status__in=[
                ProposalDraft.Status.PENDING,
                ProposalDraft.Status.PROCESSING,
            ],
        ).first()
