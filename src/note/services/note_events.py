"""Note-scoped push events for notebook WebSocket clients.

Publishes a ``note_version_created`` event to a per-note channel-layer group
whenever a new ``NoteContent`` row is committed, whoever created it (editor
autosave, agent tools, system writers). Clients subscribed to
``ws/notebook/notes/<note_id>/`` use it to notice the note changed without
polling.

The contract mirrors ``research_ai.services.notebook_chat.events``:

- **Events carry identifiers, never content.** A client treats any event as a
  nudge to compare version ids and refetch, so dropped, duplicated, or
  reordered events can never show wrong data (at-least-once, advisory).
- **Emission is post-commit and best-effort.** Publishes are deferred with
  ``transaction.on_commit(robust=True)``, so an event never describes a write
  a refetch cannot yet see, and a failing channel layer can never break the
  note write it narrates.

The group is per-note (not the org-wide ``<slug>_notebook`` room) because
note read access can be narrower than org membership -- private notes must
not leak version activity to the rest of the org -- and because autosave
emits every couple of seconds while someone types, which only clients
actually viewing the note should receive.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)

# Channel-layer message type; Channels routes it to the consumer handler of
# the same name.
EVENT_TYPE = "note_version_event"

# ``type`` field of the payload delivered to clients.
NOTE_VERSION_CREATED = "note_version_created"


def note_group(note_id: int | str) -> str:
    """The channel-layer group carrying one note's events."""
    return f"notebook_note_{note_id}"


class NoteVersionEventPublisher:
    """Publishes version events to a note's channel-layer group.

    The channel layer is injectable for tests; by default each send resolves
    the configured layer at publish time, so a worker process that never
    serves WebSockets still publishes through the shared Redis backend.
    """

    def __init__(self, channel_layer=None):
        self._channel_layer = channel_layer

    def publish_created(self, version) -> None:
        """Emit ``note_version_created`` for a new ``NoteContent`` row.

        Deferred to the current transaction's commit; sends immediately when
        no transaction is active. ``robust`` so a failed send cannot cancel
        sibling commit callbacks.
        """
        data = {
            "type": NOTE_VERSION_CREATED,
            "note_id": version.note_id,
            "version_id": version.id,
            "parent_version_id": version.parent_version_id,
            "created_by": version.created_by_id,
            "created_via": version.created_via,
            "created_date": version.created_date.isoformat(),
        }
        transaction.on_commit(
            lambda: self._send(version.note_id, data),
            robust=True,
        )

    def _send(self, note_id: int, data: dict) -> None:
        try:
            layer = self._channel_layer or get_channel_layer()
            async_to_sync(layer.group_send)(
                note_group(note_id),
                {"type": EVENT_TYPE, "data": data},
            )
        except Exception:  # noqa: BLE001 - push is best-effort by contract
            logger.warning(
                "note version event publish failed (note=%s version=%s)",
                note_id,
                data.get("version_id"),
                exc_info=True,
            )
