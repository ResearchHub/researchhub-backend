import json

from channels.db import database_sync_to_async
from channels.exceptions import StopConsumer
from channels.generic.websocket import AsyncWebsocketConsumer

from note.related_models.note_model import Note
from note.services.note_events import note_group
from user.models import Organization, User

# Private-use WebSocket close codes (4000-4999), mapped to the REST statuses
# the same request would have received.
CLOSE_UNAUTHENTICATED = 4401
CLOSE_NOT_FOUND = 4404


@database_sync_to_async
def check_org_has_user(user, organization_slug):
    organization = Organization.objects.filter(slug=organization_slug)
    if organization.exists():
        organization = organization.first()
    else:
        return False
    return organization.org_has_user(user)


class NoteConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if "user" not in self.scope:
            self.close(code=401)
            raise StopConsumer

        user = self.scope["user"]
        if user.is_anonymous:
            self.close(code=401)
            raise StopConsumer
        else:
            kwargs = self.scope["url_route"]["kwargs"]
            organization_slug = kwargs["organization_slug"]

            org_has_user = await check_org_has_user(user, organization_slug)
            if not org_has_user:
                self.close(code=401)
                raise StopConsumer

            room = f"{organization_slug}_notebook"
            self.room_group_name = room
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept(subprotocol="Token")

    async def disconnect(self, close_code):
        if close_code == 401 or not hasattr(self, "room_group_name"):
            return
        else:
            await self.channel_layer.group_discard(
                self.room_group_name, self.channel_name
            )
        raise StopConsumer

    async def send_note_notification(self, event):
        data = event["data"]
        await self.send(text_data=json.dumps(data))


def _note_rejection(user, note_id: int) -> int | None:
    """Why ``user`` may not watch this note, or ``None`` to admit them.

    Admission matches the note's read permissions exactly (the
    ``HasAccessPermission`` predicate): any non-NO_ACCESS user- or org-level
    permission on the unified document. An invisible note closes with the
    same code as a missing one so nothing about its existence leaks.
    """
    note = Note.objects.filter(id=note_id, unified_document__is_removed=False).first()
    if note is None or not note.permissions.has_user(user):
        return CLOSE_NOT_FOUND
    return None


@database_sync_to_async
def _note_rejection_code(user, note_id: int) -> int | None:
    return _note_rejection(user, note_id)


@database_sync_to_async
def _revalidation_code(user_id: int, note_id: int) -> int | None:
    """The connect-time gate, re-run from fresh database state.

    The scope's user object and the group membership both reflect
    connect time; deactivation or a permission revocation since then
    (``make_private``, permission removal) must stop event delivery, not
    just future connects.
    """
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        return CLOSE_UNAUTHENTICATED
    return _note_rejection(user, note_id)


class NoteVersionConsumer(AsyncWebsocketConsumer):
    """Subscribes one client to one note's events (``ws/notebook/notes/<id>/``).

    Carries the ``note_version_created`` nudges published by
    ``note.services.note_events`` whenever a new content version is committed,
    whoever wrote it. Payloads are ids and metadata only; a client should
    refetch on any event and treat the socket as droppable (the REST API
    remains the source of truth).
    """

    async def connect(self):
        user = self.scope.get("user")
        # ``is_active`` alongside ``is_anonymous``: deactivating an account
        # must revoke this socket the same way DRF revokes the REST API,
        # even while the account's auth token still resolves to a user.
        if user is None or user.is_anonymous or not user.is_active:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        # The route constrains this to digits; the cast normalizes away
        # artifacts like leading zeros so the group name always matches the
        # one the publisher derives from model ids.
        note_id = int(self.scope["url_route"]["kwargs"]["note_id"])

        rejection = await _note_rejection_code(user, note_id)
        if rejection is not None:
            await self.close(code=rejection)
            return

        self._user_id = user.id
        self._note_id = note_id
        self.group_name = note_group(note_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # The client offers ("Token", <key>) as subprotocols for
        # TokenAuthMiddleware; echo the name back like the other consumers.
        await self.accept(subprotocol="Token")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def note_version_event(self, event):
        """Forward one published note event to the client.

        Access is re-checked per event: group membership only proves the
        client was admitted once, and a since-revoked viewer must not keep
        receiving a private note's activity.
        """
        rejection = await _revalidation_code(self._user_id, self._note_id)
        if rejection is not None:
            await self.close(code=rejection)
            return
        await self.send(text_data=json.dumps(event["data"]))
