import logging

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import ProposalDraft, SearchExpert
from research_ai.permissions import ResearchAIBudgetPermission
from research_ai.serializers import (
    ProposalDraftCreateSerializer,
    ProposalDraftSerializer,
)
from research_ai.services.agent import split_model_ref
from research_ai.services.agent.model_capabilities import validate_generation_options
from research_ai.services.proposal_draft.cancel_service import (
    ProposalDraftCancelService,
)
from research_ai.services.usage_budget import (
    ModelNotAllowedError,
    UsageLimitExceededError,
    UsageWorkInProgressError,
    atomic_turn_admission,
    effective_generation_options,
    resolve_ai_tier,
    resolve_default_model,
)
from research_ai.services.usage_budget.reservation import reservation_deadline
from research_ai.tasks import run_proposal_draft_task
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)


def _search_experts_for(user):
    queryset = SearchExpert.objects.select_related("expert_search")
    if user.is_moderator_or_editor():
        return queryset
    return queryset.filter(expert_search__created_by=user)


def _proposal_drafts_for(user):
    queryset = ProposalDraft.objects.all()
    if user.is_moderator_or_editor():
        return queryset
    return queryset.filter(created_by=user)


def _active_draft_for(search_expert):
    return ProposalDraft.objects.filter(
        search_expert=search_expert,
        status__in=[
            ProposalDraft.Status.PENDING,
            ProposalDraft.Status.PROCESSING,
        ],
    ).first()


def _active_draft_conflict(active):
    return Response(
        {
            "detail": "A proposal draft is already in progress for this expert",
            "proposal_draft_id": active.id,
        },
        status=status.HTTP_409_CONFLICT,
    )


class ProposalDraftCreateView(APIView):
    """
    View for creating proposal draft jobs.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIBudgetPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request):
        """
        Create a new proposal draft job for a given search expert.
        If a draft is already in progress for that expert,
        return a 409 Conflict with the existing draft ID.
        """
        serializer = ProposalDraftCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        search_expert_id = serializer.validated_data["search_expert_id"]
        search_expert = get_object_or_404(
            _search_experts_for(request.user), id=search_expert_id
        )

        active = _active_draft_for(search_expert)
        if active is not None:
            return _active_draft_conflict(active)

        try:
            policy = resolve_ai_tier(request.user)
            model_ref = serializer.validated_data["model"] or resolve_default_model(
                policy
            )
            effort, thinking = effective_generation_options(
                policy,
                effort=serializer.validated_data.get("effort"),
                thinking=serializer.validated_data.get("thinking"),
            )
        except ValueError as error:
            return Response(
                {"detail": str(error), "code": getattr(error, "code", "invalid")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        provider_name, model_id = split_model_ref(model_ref)
        try:
            validate_generation_options(
                provider_name,
                model_id or "",
                effort=effort,
                thinking=thinking,
                temperature=serializer.validated_data.get("temperature"),
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        requested_options = {
            key: serializer.validated_data[key]
            for key in ("temperature",)
            if key in serializer.validated_data
        }
        if effort is not None:
            requested_options["effort"] = effort
        if thinking is not None:
            requested_options["thinking"] = thinking

        try:
            with atomic_turn_admission(
                request.user,
                model_ref,
                effort=effort,
                thinking=thinking,
            ):
                draft = ProposalDraft.objects.create(
                    search_expert=search_expert,
                    created_by=request.user,
                    status=ProposalDraft.Status.PENDING,
                    step=ProposalDraft.Step.QUEUED,
                    model_ref=model_ref,
                    run_config=requested_options,
                    usage_reservation_expires_at=reservation_deadline(),
                )
        except UsageLimitExceededError as error:
            return Response(
                {"code": error.code, **error.status.as_dict()},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except ModelNotAllowedError as error:
            return Response(
                {"detail": str(error), "code": error.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except UsageWorkInProgressError as error:
            return Response(
                {"detail": str(error), "code": error.code},
                status=status.HTTP_409_CONFLICT,
            )
        except IntegrityError:
            active = _active_draft_for(search_expert)
            if active is not None:
                return _active_draft_conflict(active)
            raise
        try:
            run_proposal_draft_task.delay(draft.id)
        except Exception:  # noqa: BLE001 - a broker refusal must release the job
            logger.exception("could not queue proposal draft %s", draft.id)
            ProposalDraft.objects.filter(
                id=draft.id,
                status=ProposalDraft.Status.PENDING,
            ).update(
                status=ProposalDraft.Status.FAILED,
                error_message="Could not queue proposal drafting task",
                usage_reservation_expires_at=None,
            )
            return Response(
                {
                    "detail": "Could not queue proposal drafting task",
                    "code": "proposal_draft_enqueue_failed",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            ProposalDraftSerializer(draft).data,
            status=status.HTTP_201_CREATED,
        )


class ProposalDraftDetailView(APIView):
    """
    View for polling the status of a proposal draft job.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIBudgetPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request, draft_id):
        draft = get_object_or_404(_proposal_drafts_for(request.user), id=draft_id)

        return Response(ProposalDraftSerializer(draft).data)


class ProposalDraftCancelView(APIView):
    """
    View for stopping a queued or in-flight proposal draft job.

    Idempotent by design: cancelling a draft that already finished -- or that
    someone else cancelled a moment earlier -- is a success reporting
    ``cancelled: false``, so a client that cannot tell whether its first request
    landed can simply send it again. The draft is returned either way, since the
    state the caller wanted to change is the state worth reporting back.

    Cancellation is cooperative: this records the decision and returns without
    waiting for the worker, which stops at its next checkpoint. The draft is
    terminal from this moment even while a model call is still in flight.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIBudgetPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request, draft_id):
        draft = get_object_or_404(_proposal_drafts_for(request.user), id=draft_id)
        cancelled = ProposalDraftCancelService().cancel(
            draft, cancelled_by=request.user
        )
        draft.refresh_from_db()

        return Response({"cancelled": cancelled, **ProposalDraftSerializer(draft).data})
