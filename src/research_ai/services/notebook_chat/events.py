"""Turn-lifecycle push events for notebook chat WebSocket clients.

The polling projection (``?activity=live``) is the source of truth for a
chat's state; its weakness is latency, not correctness -- a client learns of
progress only at its next poll. This module closes that gap by publishing a
small event to a per-conversation channel-layer group at every point a turn's
durable state changes, so a subscribed client can refetch immediately instead
of waiting out its interval.

Two properties keep this layer simple and safe to lose:

- **Events carry identifiers, never state.** A client reacts to any event the
  same way -- refetch the conversation -- so a dropped, duplicated, or
  reordered event can never show wrong data, only later data. Polling remains
  the repair path; the socket is purely a latency optimization.
- **Emission is post-commit and best-effort.** Every publish is deferred with
  ``transaction.on_commit(robust=True)``, so an event can never describe a
  write the triggered refetch cannot yet see, and a failing channel layer can
  never break the write it narrates (or starve later commit callbacks, such
  as the one that queues the worker task).

The group is scoped to one conversation because chats are private to their
creator: the consumer admits only the owner, so events never reach an
org-wide room the way note notifications do.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)

# Channel-layer message type; Channels routes it to the consumer handler of
# the same name.
EVENT_TYPE = "notebook_chat_event"

# Event kinds, in rough lifecycle order. ``TURN_PROGRESS`` fires on every
# durable trace append (assistant turns and tool results alike); the terminal
# kinds are advisory -- the refetch, not the kind, is what a client should
# trust for the execution's final status.
TURN_QUEUED = "turn_queued"
TURN_PROGRESS = "turn_progress"
TURN_FINISHED = "turn_finished"
TURN_FAILED = "turn_failed"
TURN_CANCELLED = "turn_cancelled"


def conversation_group(conversation_id: int | str) -> str:
    """The channel-layer group carrying one chat's turn events."""
    return f"notebook_chat_{conversation_id}"


class ConversationEventPublisher:
    """Publishes turn events to a conversation's channel-layer group.

    The channel layer is injectable for tests; by default each send resolves
    the configured layer at publish time, so a worker process that never
    serves WebSockets still publishes through the shared Redis backend.
    """

    def __init__(self, channel_layer=None):
        self._channel_layer = channel_layer

    def publish(self, conversation_id: int, execution_id: int, kind: str) -> None:
        """Emit ``kind`` for ``execution_id`` once the current transaction commits.

        Outside a transaction this sends immediately (``on_commit`` semantics),
        which is the worker path: the recorder's writes commit before its hooks
        return. ``robust`` because a lost nudge costs one poll interval, while
        an exception here could otherwise cancel sibling commit callbacks.
        """
        transaction.on_commit(
            lambda: self._send(conversation_id, execution_id, kind),
            robust=True,
        )

    def _send(self, conversation_id: int, execution_id: int, kind: str) -> None:
        try:
            layer = self._channel_layer or get_channel_layer()
            if layer is None:
                return
            async_to_sync(layer.group_send)(
                conversation_group(conversation_id),
                {
                    "type": EVENT_TYPE,
                    "data": {
                        "conversation_id": conversation_id,
                        "execution_id": execution_id,
                        "kind": kind,
                    },
                },
            )
        except Exception:  # noqa: BLE001 - push is best-effort by contract
            logger.warning(
                "notebook chat event publish failed (conversation=%s kind=%s)",
                conversation_id,
                kind,
                exc_info=True,
            )


class PublishingRecorder:
    """Wraps a turn's recorder to publish an event after each durable write.

    The wrapped recorder stays the authority on persistence and its contracts
    (``requires_durable_messages``, ``is_active``, ``terminal_observed`` --
    everything undefined here is delegated). This wrapper only appends a
    post-write nudge, and only for writes that actually landed: publish after
    the wrapped call returns, never when it raises, and never when a terminal
    hook reports that it performed no transition of its own. A cancelled run
    therefore emits nothing on its way down --
    whether it unwinds through a refused write (``InterruptedError``) into
    the failure hook or races cancellation to the finish hook, the row was
    sealed from outside and the hook finds nothing left to record. The
    sealing path (cancellation) already published the authoritative event;
    announcing ``turn_failed`` or ``turn_finished`` over it would hand
    subscribers a contradiction.
    """

    def __init__(
        self,
        recorder,
        publisher: ConversationEventPublisher,
        *,
        conversation_id: int,
        execution_id: int,
    ):
        self._recorder = recorder
        self._publisher = publisher
        self._conversation_id = conversation_id
        self._execution_id = execution_id

    def __getattr__(self, name):
        return getattr(self._recorder, name)

    def _publish(self, kind: str) -> None:
        self._publisher.publish(self._conversation_id, self._execution_id, kind)

    def record_message(self, message, *, turn=None) -> None:
        self._recorder.record_message(message, turn=turn)
        self._publish(TURN_PROGRESS)

    def on_run_finished(self, result) -> None:
        # Only an explicit ``False`` report suppresses the event: it means the
        # hook found the row already sealed from outside and discarded the
        # result, so the sealing path's event stands alone. A recorder that
        # does not track transitions returns ``None`` and keeps its events.
        # On a real finish the wrapped hook also publishes the assistant's
        # reply to the chat before returning, so this event's refetch already
        # sees the answer.
        if self._recorder.on_run_finished(result) is False:
            return
        self._publish(TURN_FINISHED)

    def on_run_failed(self, error: Exception) -> None:
        # Same rule as the finish hook. A report of no transition here is the
        # cancelled run's own unwinding reaching this hook (an interruption,
        # or a late failure) after cancellation already sealed the row and
        # told the subscribers.
        if self._recorder.on_run_failed(error) is False:
            return
        self._publish(TURN_FAILED)
