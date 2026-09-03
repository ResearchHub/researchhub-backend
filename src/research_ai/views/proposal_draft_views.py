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
from research_ai.services.proposal_draft.cancel_service import (
    ProposalDraftCancelService,
)
from research_ai.services.proposal_draft.create_service import (
    ProposalDraftAlreadyActiveError,
    ProposalDraftCreateService,
    ProposalDraftEnqueueError,
)
from research_ai.services.usage_budget import (
    ModelNotAllowedError,
    UsageLimitExceededError,
    UsageWorkInProgressError,
)
from user.permissions import IsModerator, UserIsEditor


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

        try:
            draft = ProposalDraftCreateService().create(
                search_expert=search_expert,
                created_by=request.user,
                model_ref=serializer.validated_data["model"],
                effort=serializer.validated_data.get("effort"),
                thinking=serializer.validated_data.get("thinking"),
                temperature=serializer.validated_data.get("temperature"),
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
        except ProposalDraftAlreadyActiveError as error:
            return _active_draft_conflict(error.draft)
        except ProposalDraftEnqueueError as error:
            return Response(
                {
                    "detail": str(error),
                    "code": error.code,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

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
