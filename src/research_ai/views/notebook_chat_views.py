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
from research_ai.services.notebook_chat import NotebookChatService
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
    """Read the user's assistant conversation on a note."""

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
        return Response(service.chat.representation(conversation))


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
