"""API for the research assistant chat.

The assistant is the notebook chat without a note: the collection lives at
``assistant/chats/`` and every other route addresses one chat by id. Chats
are private to their creator, so another user's chat id is a 404. Access is
gated exactly as the notebook chat: authentication, a non-blocked Research AI
tier, and the editor-or-moderator rollout gate.
"""

import logging

from django.http import Http404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import AgentConversation
from research_ai.permissions import ResearchAIBudgetPermission
from research_ai.serializers import (
    NotebookChatCreateSerializer,
    NotebookChatMessageCreateSerializer,
    NotebookChatUpdateSerializer,
)
from research_ai.services.agent_persistence import AgentConversationBusyError
from research_ai.services.assistant_chat import AssistantChatService
from research_ai.services.notebook_chat import ACTIVITY_ALL, ACTIVITY_LIVE
from research_ai.services.usage_budget import (
    UsageLimitExceededError,
    UsageWorkInProgressError,
)
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)

ASSISTANT_CHAT_PERMISSIONS = [
    IsAuthenticated,
    ResearchAIBudgetPermission,
    UserIsEditor | IsModerator,
]


def _get_conversation_or_404(
    service: AssistantChatService, user, conversation_id: int
) -> AgentConversation:
    conversation = service.get_conversation(user, conversation_id)
    if conversation is None:
        raise Http404
    return conversation


class AssistantChatListCreateView(APIView):
    """List the user's assistant chats, or start a new one."""

    permission_classes = ASSISTANT_CHAT_PERMISSIONS

    def get(self, request):
        return Response(
            {"chats": AssistantChatService().list_conversations(request.user)}
        )

    def post(self, request):
        serializer = NotebookChatCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = AssistantChatService()
        conversation = service.create_conversation(
            request.user, title=serializer.validated_data["title"]
        )
        return Response(
            service.representation(conversation), status=status.HTTP_201_CREATED
        )


class AssistantChatDetailView(APIView):
    """Read or rename one chat; ``?activity=live`` is the polling form."""

    permission_classes = ASSISTANT_CHAT_PERMISSIONS

    def get(self, request, conversation_id):
        service = AssistantChatService()
        conversation = _get_conversation_or_404(service, request.user, conversation_id)
        scope = (
            ACTIVITY_LIVE
            if request.query_params.get("activity") == ACTIVITY_LIVE
            else ACTIVITY_ALL
        )
        return Response(service.representation(conversation, activity_scope=scope))

    def patch(self, request, conversation_id):
        serializer = NotebookChatUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = AssistantChatService()
        conversation = _get_conversation_or_404(service, request.user, conversation_id)
        service.rename_conversation(conversation, serializer.validated_data["title"])
        return Response(
            {"conversation_id": conversation.id, "title": conversation.title}
        )


class AssistantChatMessageView(APIView):
    """Send a message to one chat; the turn runs asynchronously."""

    permission_classes = ASSISTANT_CHAT_PERMISSIONS

    def post(self, request, conversation_id):
        serializer = NotebookChatMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = AssistantChatService()
        conversation = _get_conversation_or_404(service, request.user, conversation_id)
        try:
            execution = service.submit_message(
                conversation,
                serializer.validated_data["message"],
                model_ref=serializer.validated_data["model"] or None,
                effort=serializer.validated_data.get("effort"),
                thinking=serializer.validated_data.get("thinking"),
                temperature=serializer.validated_data.get("temperature"),
            )
        except AgentConversationBusyError:
            return Response(
                {"detail": "The assistant is still working on a previous message."},
                status=status.HTTP_409_CONFLICT,
            )
        except UsageWorkInProgressError as error:
            return Response(
                {"detail": str(error), "code": error.code},
                status=status.HTTP_409_CONFLICT,
            )
        except UsageLimitExceededError as error:
            return Response(
                {"code": error.code, **error.status.as_dict()},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except ValueError as error:
            return Response(
                {
                    "detail": str(error),
                    **({"code": error.code} if getattr(error, "code", None) else {}),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "conversation_id": execution.conversation_id,
                "execution_id": execution.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AssistantChatCancelView(APIView):
    """Stop one chat's in-flight turn; idempotent like the notebook cancel."""

    permission_classes = ASSISTANT_CHAT_PERMISSIONS

    def post(self, request, conversation_id):
        service = AssistantChatService()
        conversation = _get_conversation_or_404(service, request.user, conversation_id)
        execution = service.cancel_active_turn(conversation)
        if execution is None:
            return Response({"cancelled": False, "execution_id": None})
        return Response({"cancelled": True, "execution_id": execution.id})
