"""WebSocket consumers for research AI features.

``NotebookChatConsumer`` subscribes one client to one chat's turn events
(``ws/notebook/notes/<note_id>/chats/<conversation_id>/``);
``AssistantChatConsumer`` does the same for a note-less assistant chat
(``ws/assistant/chats/<conversation_id>/``). Lifecycle events
are small refetch nudges; ``stream_delta`` events append transient text or
readable thinking to the matching active execution. The payload is forwarded
verbatim. The ``?activity=live`` projection remains the recovery path: it
carries the newest bounded stream snapshot while a turn is active. Clients
must ignore transient deltas once that execution has settled.

Admission mirrors the REST contract in ``notebook_chat_views`` and must be
kept in sync with ``NOTEBOOK_CHAT_PERMISSIONS`` there: authentication
(4401 -- including a deactivated account, which ``TokenAuthMiddleware``
still resolves from its lingering token but DRF's ``TokenAuthentication``
refuses), the editor-or-moderator rollout gate (4403, the REST 403), and
owner-scoped resolution of the note and conversation (4404, the REST 404).
Resolution failures close with the same code whether the chat does not
exist, belongs to someone else, or sits on an invisible note -- the group is
per-conversation and owner-only precisely because chats are private, unlike
the org-wide room ``NoteConsumer`` uses for note notifications.
"""

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from note.related_models.note_model import Note
from research_ai.services.assistant_chat import AssistantChatService
from research_ai.services.notebook_chat import NotebookChatService
from research_ai.services.notebook_chat.events import conversation_group
from research_ai.services.usage_budget import resolve_ai_tier

# Private-use WebSocket close codes (4000-4999), mapped to the REST statuses
# the same request would have received.
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


def _gate_rejection_code(user) -> int | None:
    """The Research AI tier and editor-or-moderator rollout gates."""
    if resolve_ai_tier(user).name == "blocked":
        return CLOSE_FORBIDDEN
    if not (user.moderator or user.is_hub_editor()):
        return CLOSE_FORBIDDEN
    return None


@database_sync_to_async
def _notebook_rejection_code(user, note_id: int, conversation_id: int) -> int | None:
    """Why ``user`` may not watch this notebook chat, or ``None`` to admit them.

    One database hop covering the REST permission stack: the gates, then note
    visibility and conversation ownership exactly as the views resolve them.
    """
    rejection = _gate_rejection_code(user)
    if rejection is not None:
        return rejection
    note = Note.objects.filter(id=note_id, unified_document__is_removed=False).first()
    if note is None or not note.permissions.has_user(user):
        return CLOSE_NOT_FOUND
    service = NotebookChatService()
    if service.get_conversation(note, user, conversation_id) is None:
        return CLOSE_NOT_FOUND
    return None


@database_sync_to_async
def _assistant_rejection_code(user, conversation_id: int) -> int | None:
    """Why ``user`` may not watch this assistant chat, or ``None`` to admit them."""
    rejection = _gate_rejection_code(user)
    if rejection is not None:
        return rejection
    if AssistantChatService().get_conversation(user, conversation_id) is None:
        return CLOSE_NOT_FOUND
    return None


class _ConversationConsumer(AsyncWebsocketConsumer):
    """Admit the owner of one chat and forward its turn events."""

    async def rejection_code(self, user, kwargs: dict) -> int | None:
        raise NotImplementedError

    async def connect(self):
        user = self.scope.get("user")
        # ``is_active`` alongside ``is_anonymous``: deactivating an account
        # must revoke this socket the same way DRF revokes the REST API,
        # even while the account's auth token still resolves to a user.
        if user is None or user.is_anonymous or not user.is_active:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        # The routes constrain ids to digits; the casts normalize away
        # artifacts like leading zeros so the group name always matches the
        # one the publisher derives from model ids.
        kwargs = {
            key: int(value) for key, value in self.scope["url_route"]["kwargs"].items()
        }
        rejection = await self.rejection_code(user, kwargs)
        if rejection is not None:
            await self.close(code=rejection)
            return

        self.group_name = conversation_group(kwargs["conversation_id"])
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # The client offers ("Token", <key>) as subprotocols for
        # TokenAuthMiddleware; echo the name back like the other consumers.
        await self.accept(subprotocol="Token")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notebook_chat_event(self, event):
        """Forward one published turn event to the client."""
        await self.send(text_data=json.dumps(event["data"]))


class NotebookChatConsumer(_ConversationConsumer):
    async def rejection_code(self, user, kwargs: dict) -> int | None:
        return await _notebook_rejection_code(
            user, kwargs["note_id"], kwargs["conversation_id"]
        )


class AssistantChatConsumer(_ConversationConsumer):
    async def rejection_code(self, user, kwargs: dict) -> int | None:
        return await _assistant_rejection_code(user, kwargs["conversation_id"])
