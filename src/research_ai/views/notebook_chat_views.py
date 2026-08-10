"""API for the notebook chat assistant.

Rollout is gated to hub editors and moderators for now (same gate as the
proposal-draft views); within that group, access mirrors the note itself:
anyone who can view the note can read the chat and send messages (the agent
runs with the requester's permissions, so its edit tool refuses writes for
viewers). A note the user cannot view is reported as 404 rather than 403 so
its existence is not leaked -- the same contract as ``NoteToolset``.
"""

import logging

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from note.related_models.note_model import Note
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import NotebookChatMessageCreateSerializer
from research_ai.services.agent_persistence import AgentConversationBusyError
from research_ai.services.notebook_chat import (
    ACTIVITY_ALL,
    ACTIVITY_LIVE,
    NotebookChatService,
)
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)


def _get_viewable_note_or_404(note_id: int, user) -> Note:
    # Soft-deleted notes do not exist here either -- the same visibility rule
    # as NoteViewSet and NoteToolset.
    note = get_object_or_404(Note, id=note_id, unified_document__is_removed=False)
    # Same predicate as HasAccessPermission, mirroring NoteToolset reads.
    if not note.permissions.has_user(user):
        raise Http404
    return note


class NotebookChatView(APIView):
    """Read the user's assistant conversation on a note.

    ``?activity=live`` is the polling form: it recomputes the activity feed
    only for turns the client may not yet hold settled -- active ones, and
    ones whose last change (settling, or a delayed answer publication) is
    recent enough that no poll has necessarily seen it -- and omits the
    ``activity`` key for the rest, which a client is expected to already hold
    from its first load. Use it while watching a turn; use the
    default for the initial fetch. Any other value falls back to the full
    projection, so a stale or mistyped client parameter costs performance
    rather than correctness.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def get(self, request, note_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        service = NotebookChatService()
        conversation = service.get_conversation(note, request.user)
        if conversation is None:
            return Response({"conversation_id": None, "messages": [], "executions": []})
        scope = (
            ACTIVITY_LIVE
            if request.query_params.get("activity") == ACTIVITY_LIVE
            else ACTIVITY_ALL
        )
        return Response(service.representation(conversation, activity_scope=scope))


class NotebookChatMessageView(APIView):
    """Send a message to the note's assistant; the turn runs asynchronously."""

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request, note_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        serializer = NotebookChatMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = NotebookChatService()
        try:
            execution = service.submit_message(
                note, request.user, serializer.validated_data["message"]
            )
        except AgentConversationBusyError:
            return Response(
                {"detail": "The assistant is still working on a previous message."},
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "conversation_id": execution.conversation_id,
                "execution_id": execution.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class NotebookChatCancelView(APIView):
    """Stop the note assistant's in-flight turn.

    Idempotent by design: cancelling when nothing is running -- or when the
    turn finished a moment earlier -- is a success reporting ``cancelled:
    false``, not an error, because the client cannot know which side of that
    race it is on when the user clicks stop.
    """

    permission_classes = [
        IsAuthenticated,
        ResearchAIPermission,
        UserIsEditor | IsModerator,
    ]

    def post(self, request, note_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        execution = NotebookChatService().cancel_active_turn(note, request.user)
        if execution is None:
            return Response({"cancelled": False, "execution_id": None})
        return Response({"cancelled": True, "execution_id": execution.id})
