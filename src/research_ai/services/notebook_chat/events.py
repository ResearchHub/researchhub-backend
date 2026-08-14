"""Turn-lifecycle push events for notebook chat WebSocket clients.

The polling projection (``?activity=live``) is the source of truth for durable
chat state; its weakness is latency, not correctness. This module closes that
gap with two kinds of per-conversation event: identifiers that nudge a refetch
after a durable change, and bounded transient model-output deltas for text and
readable thinking. A cache snapshot lets the REST projection repair a dropped
or reordered transient frame.

Two properties keep this layer simple and safe to lose:

- **Durable events carry identifiers, never state.** A client refetches for
  lifecycle events. Stream events carry only append deltas plus a monotonic
  sequence; any sequence gap is repaired from the REST snapshot.
- **Emission is best-effort.** Durable events are deferred with
  ``transaction.on_commit(robust=True)``. Stream snapshots are periodically
  checkpointed before their corresponding delta is sent. A failing channel
  layer therefore never breaks the turn, and REST remains a recovery path.

The group is scoped to one conversation because chats are private to their
creator: the consumer admits only the owner, so events never reach an
org-wide room the way note notifications do.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from research_ai.services.notebook_chat.streaming import (
    STREAM_DELTA,
    ExecutionStreamStore,
    NotebookStreamBuffer,
)

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

        Sends immediately when no transaction is active. ``robust`` so a
        failed send cannot cancel sibling commit callbacks.
        """
        transaction.on_commit(
            lambda: self._send(conversation_id, execution_id, kind),
            robust=True,
        )

    def _send(self, conversation_id: int, execution_id: int, kind: str) -> None:
        self._send_data(
            conversation_id,
            {
                "conversation_id": conversation_id,
                "execution_id": execution_id,
                "kind": kind,
            },
        )

    def publish_stream(
        self,
        conversation_id: int,
        execution_id: int,
        *,
        stream_id: str,
        sequence: int,
        iteration: int,
        deltas: list[dict],
    ) -> None:
        """Publish one transient stream batch immediately.

        Recovery snapshots are checkpointed independently of these small
        frames, so no database transaction needs to commit before the frame is
        safe to observe.
        """
        self._send_data(
            conversation_id,
            {
                "conversation_id": conversation_id,
                "execution_id": execution_id,
                "kind": STREAM_DELTA,
                "stream_id": stream_id,
                "sequence": sequence,
                "iteration": iteration,
                "deltas": deltas,
            },
        )

    def _send_data(self, conversation_id: int, data: dict) -> None:
        try:
            layer = self._channel_layer or get_channel_layer()
            async_to_sync(layer.group_send)(
                conversation_group(conversation_id),
                {
                    "type": EVENT_TYPE,
                    "data": data,
                },
            )
        except Exception:  # noqa: BLE001 - push is best-effort by contract
            logger.warning(
                "notebook chat event publish failed (conversation=%s kind=%s)",
                conversation_id,
                data.get("kind"),
                exc_info=True,
            )


class PublishingRecorder:
    """Wraps a turn's recorder to publish an event after each durable write.

    Everything undefined here is delegated to the wrapped recorder. Events
    fire only for writes that landed: never when the wrapped call raises,
    and never when a terminal hook reports it performed no transition --
    that run was sealed from outside (cancelled), and the sealing path
    already published the authoritative event.
    """

    def __init__(
        self,
        recorder,
        publisher: ConversationEventPublisher,
        *,
        conversation_id: int,
        execution_id: int,
        stream_store: ExecutionStreamStore | None = None,
    ):
        self._recorder = recorder
        self._publisher = publisher
        self._conversation_id = conversation_id
        self._execution_id = execution_id
        self._stream = NotebookStreamBuffer(
            conversation_id=conversation_id,
            execution_id=execution_id,
            store=(ExecutionStreamStore() if stream_store is None else stream_store),
            publisher=publisher,
            is_active=getattr(recorder, "is_active", None),
        )

    def __getattr__(self, name):
        return getattr(self._recorder, name)

    def _publish(self, kind: str) -> None:
        self._publisher.publish(self._conversation_id, self._execution_id, kind)

    def _stream_best_effort(self, operation: str, callback, *args) -> None:
        try:
            callback(*args)
        except Exception:  # noqa: BLE001 - previews must never break a turn
            logger.warning(
                "notebook chat stream %s failed (execution=%s)",
                operation,
                self._execution_id,
                exc_info=True,
            )

    def record_message(self, message, *, turn=None) -> None:
        self._stream_best_effort("flush", self._stream.flush)
        self._recorder.record_message(message, turn=turn)
        if turn is not None:
            # The complete provider turn is now durable and the REST activity
            # projection supersedes its transient preview.
            self._stream_best_effort("clear", self._stream.clear)
        self._publish(TURN_PROGRESS)

    def record_stream_event(self, iteration, event) -> None:
        self._stream_best_effort("append", self._stream.append, iteration, event)

    def flush_stream_events(self) -> None:
        self._stream_best_effort("flush", self._stream.flush)

    def _clear_stream(self) -> None:
        self._stream_best_effort("clear", self._stream.clear)

    def on_run_finished(self, result) -> None:
        # Only an explicit False suppresses; None (a recorder that does not
        # track transitions) keeps the event.
        if self._recorder.on_run_finished(result) is False:
            self._clear_stream()
            return
        self._clear_stream()
        self._publish(TURN_FINISHED)

    def on_run_failed(self, error: Exception) -> None:
        if self._recorder.on_run_failed(error) is False:
            self._clear_stream()
            return
        self._clear_stream()
        self._publish(TURN_FAILED)
