"""AG-UI endpoints for notebook chats, for CopilotKit.

Both take an AG-UI ``RunAgentInput`` and answer with a server-sent AG-UI event
stream (see ``ChatRelay``):

- ``.../agui/`` runs the agent. When the input ends with a user message the
  chat does not hold yet, that message starts a turn exactly as the messages
  endpoint would -- the same validation, model controls (``model``,
  ``effort``, ``thinking``, ``temperature``) and ``file_ids`` read from
  ``forwardedProps`` -- and the stream follows the turn. Otherwise it behaves
  like connect.
- ``.../agui/connect/`` never starts a turn. It sends the chat's history and,
  when a turn is running, follows it to the end; this is how a client loads a
  chat or rejoins a turn after a reload.

The input's message list is not trusted as history: the chat's persisted
messages are the history, and anything the client sends besides the new user
message is ignored. Stopping a turn stays on the existing cancel endpoint;
closing the stream only stops watching.

Everything that can fail before streaming -- auth, the Research AI gates,
resolution, validation, a busy chat, the usage budget -- fails as a plain JSON
error response with the same status codes as the REST API, as the AG-UI HTTP
binding asks.
"""

from ag_ui.core import RunAgentInput, UserMessage
from asgiref.sync import sync_to_async
from django.http import StreamingHttpResponse
from pydantic import ValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import AgentConversation
from research_ai.serializers import NotebookChatMessageCreateSerializer
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.services.notebook_chat.agui import is_persisted_message_id
from research_ai.services.notebook_chat.agui_relay import ChatRelay
from research_ai.views.notebook_chat_views import (
    NOTEBOOK_CHAT_PERMISSIONS,
    _get_conversation_or_404,
    _get_viewable_note_or_404,
    submit_message,
)

# ``forwardedProps`` keys passed through to the message serializer.
_FORWARDED_FIELDS = ("model", "effort", "thinking", "temperature", "file_ids")


class NotebookChatAguiRunView(APIView):
    """Run the chat's agent, or rejoin it, as an AG-UI event stream."""

    permission_classes = NOTEBOOK_CHAT_PERMISSIONS
    starts_turns = True

    def perform_content_negotiation(self, request, force=False):
        # The client asks for text/event-stream; responses DRF renders here
        # are the pre-stream errors, which are JSON.
        return super().perform_content_negotiation(request, force=True)

    def post(self, request, note_id, conversation_id):
        note = _get_viewable_note_or_404(note_id, request.user)
        service = NotebookChatService()
        conversation = _get_conversation_or_404(
            service, note, request.user, conversation_id
        )
        try:
            run_input = RunAgentInput.model_validate(request.data)
        except ValidationError as error:
            return Response(
                {
                    "detail": "Invalid AG-UI run input.",
                    "errors": error.errors(
                        include_url=False, include_context=False, include_input=False
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        execution_id = None
        message = _new_user_message(run_input) if self.starts_turns else None
        if message is not None:
            props = run_input.forwarded_props
            props = props if isinstance(props, dict) else {}
            serializer = NotebookChatMessageCreateSerializer(
                data={
                    **{key: props[key] for key in _FORWARDED_FIELDS if key in props},
                    "message": _message_text(message),
                }
            )
            serializer.is_valid(raise_exception=True)
            execution = submit_message(
                service, note, conversation, serializer.validated_data
            )
            if isinstance(execution, Response):
                return execution
            execution_id = execution.id

        relay = ChatRelay(
            conversation_id=conversation.id,
            thread_id=run_input.thread_id,
            run_id=run_input.run_id,
            load_chat=_chat_loader(service, conversation),
        )
        response = StreamingHttpResponse(
            relay.stream(execution_id), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        # Proxies that buffer would hold back every event until the turn ends.
        response["X-Accel-Buffering"] = "no"
        return response


class NotebookChatAguiConnectView(NotebookChatAguiRunView):
    """Load a chat's history and rejoin its running turn, if any."""

    starts_turns = False


def _new_user_message(run_input: RunAgentInput) -> UserMessage | None:
    """The input's trailing user message, unless the chat already holds it."""
    if not run_input.messages:
        return None
    last = run_input.messages[-1]
    if not isinstance(last, UserMessage) or is_persisted_message_id(last.id):
        return None
    return last


def _message_text(message: UserMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        part.text for part in message.content if getattr(part, "type", "") == "text"
    )


def _chat_loader(service: NotebookChatService, conversation: AgentConversation):
    def load(scope: str) -> dict:
        return service.representation(conversation, activity_scope=scope)

    return sync_to_async(load)
