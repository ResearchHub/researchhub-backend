import logging

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import ProposalDraft, SearchExpert
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    ProposalDraftCreateSerializer,
    ProposalDraftSerializer,
)
from research_ai.tasks import run_proposal_draft_task
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)


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
        ResearchAIPermission,
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

        search_expert = get_object_or_404(SearchExpert, id=search_expert_id)

        active = _active_draft_for(search_expert)
        if active is not None:
            return _active_draft_conflict(active)

        try:
            with transaction.atomic():
                draft = ProposalDraft.objects.create(
                    search_expert=search_expert,
                    created_by=request.user,
                    status=ProposalDraft.Status.PENDING,
                    step=ProposalDraft.Step.QUEUED,
                )
        except IntegrityError:
            active = _active_draft_for(search_expert)
            if active is not None:
                return _active_draft_conflict(active)
            raise
        run_proposal_draft_task.delay(draft.id)

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
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request, draft_id):
        draft = get_object_or_404(ProposalDraft, id=draft_id)

        return Response(ProposalDraftSerializer(draft).data)
