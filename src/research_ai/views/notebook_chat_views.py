"""API for the notebook chat assistant.

A user can keep any number of chats on a note; the collection lives at
``notebook/notes/<note_id>/chats/`` and every other route addresses one chat
by id. Chats are private to their creator: resolution is scoped to the
requesting user, so another collaborator's chat id -- like a note the user
cannot view -- is reported as 404 rather than 403, and nothing is leaked.

Rollout is gated to hub editors and moderators for now (same gate as the
proposal-draft views); within that group, access mirrors the note itself:
anyone who can view the note can chat on it (the agent runs with the
requester's permissions, so its edit tool refuses writes for viewers). A note
the user cannot view is likewise a 404 -- the same contract as
``NoteToolset``.
"""

import logging

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from note.related_models.note_model import Note
from research_ai.models import AgentConversation
from research_ai.permissions import ResearchAIPermission
from research_ai.serializers import (
    NotebookChatCreateSerializer,
    NotebookChatMessageCreateSerializer,
    NotebookChatUpdateSerializer,
)
from research_ai.services.agent_persistence import AgentConversationBusyError
from research_ai.services.notebook_chat import (
    ACTIVITY_ALL,
    ACTIVITY_LIVE,
    NotebookChatService,
)
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)

NOTEBOOK_CHAT_PERMISSIONS = [
    IsAuthenticated,
    ResearchAIPermission,
    UserIsEditor | IsModerator,
]


def _get_viewable_note_or_404(note_id: int, user) -> Note:
    # Soft-deleted notes do not exist here either -- the same visibility rule
    # as NoteViewSet and NoteToolset.
    note = get_object_or_404(Note, id=note_id, unified_document__is_removed=False)
    # Same predicate as HasAccessPermission, mirroring NoteToolset reads.
    if not note.permissions.has_user(user):
        raise Http404
    return note


def _get_conversation_or_404(
    service: NotebookChatService, note: Note, user, conversation_id: int
) -> AgentConversation:
    conversation = service.get_conversation(note, user, conversation_id)
    if conversation is None:
        raise Http404
    return conversation


class NotebookChatListCreateView(APIView):
    """List the user's chats on a note, or start a new one."""

    permission_classes = NOTEBOOK_CHAT_PERMISSIONS

    def get(self, request, note_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        return Response(
            {"chats": NotebookChatService().list_conversations(note, request.user)}
        )

    def post(self, request, note_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        serializer = NotebookChatCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = NotebookChatService()
        conversation = service.create_conversation(
            note, request.user, title=serializer.validated_data["title"]
        )
        return Response(
            service.representation(conversation), status=status.HTTP_201_CREATED
        )


class NotebookChatDetailView(APIView):
    """Read or rename one chat.

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

    permission_classes = NOTEBOOK_CHAT_PERMISSIONS

    def get(self, request, note_id, conversation_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        service = NotebookChatService()
        conversation = _get_conversation_or_404(
            service, note, request.user, conversation_id
        )
        scope = (
            ACTIVITY_LIVE
            if request.query_params.get("activity") == ACTIVITY_LIVE
            else ACTIVITY_ALL
        )
        return Response(service.representation(conversation, activity_scope=scope))

    def patch(self, request, note_id, conversation_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        serializer = NotebookChatUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = NotebookChatService()
        conversation = _get_conversation_or_404(
            service, note, request.user, conversation_id
        )
        service.rename_conversation(conversation, serializer.validated_data["title"])
        return Response(
            {"conversation_id": conversation.id, "title": conversation.title}
        )


class NotebookChatMessageView(APIView):
    """Send a message to one chat; the turn runs asynchronously."""

    permission_classes = NOTEBOOK_CHAT_PERMISSIONS

    def post(self, request, note_id, conversation_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        serializer = NotebookChatMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = NotebookChatService()
        conversation = _get_conversation_or_404(
            service, note, request.user, conversation_id
        )
        try:
            execution = service.submit_message(
                note, conversation, serializer.validated_data["message"]
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
    """Stop one chat's in-flight turn.

    Idempotent by design: cancelling when nothing is running -- or when the
    turn finished a moment earlier -- is a success reporting ``cancelled:
    false``, not an error, because the client cannot know which side of that
    race it is on when the user clicks stop.
    """

    permission_classes = NOTEBOOK_CHAT_PERMISSIONS

    def post(self, request, note_id, conversation_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        service = NotebookChatService()
        conversation = _get_conversation_or_404(
            service, note, request.user, conversation_id
        )
        execution = service.cancel_active_turn(conversation)
        if execution is None:
            return Response({"cancelled": False, "execution_id": None})
        return Response({"cancelled": True, "execution_id": execution.id})
