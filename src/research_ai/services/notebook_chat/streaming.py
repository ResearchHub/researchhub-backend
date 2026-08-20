"""Transient, reconnectable model-output streaming for notebook chat.

Completed provider turns still land in the agent context and trace as one
authoritative message. This module holds only a bounded user-visible preview:
small coalesced WebSocket deltas for the fast path and one cache snapshot for
reconnect and polling recovery.

The preview is deliberately best-effort. Execution status is durable and
authoritative, so clients must discard preview events after an execution has
settled. That rule keeps cancellation independent from Redis availability and
avoids distributed locking solely for presentation state.
"""

import time
from collections import OrderedDict

from django.core.cache import cache
from django.utils import timezone

from research_ai.services.agent.types import (
    StreamReset,
    TextStreamDelta,
    ThinkingStreamDelta,
)

STREAM_DELTA = "stream_delta"
STREAM_CACHE_TTL_SECONDS = 60 * 60
STREAM_FLUSH_INTERVAL_SECONDS = 0.075
STREAM_FLUSH_CHARS = 512
STREAM_ACTIVE_CHECK_INTERVAL_SECONDS = 1.0
STREAM_PUBLISH_TIMEOUT_SECONDS = 5.0
MAX_STREAM_TEXT_CHARS = 100_000
MAX_STREAM_THINKING_CHARS = 4_000


def _cache_key(execution_id: int) -> str:
    return f"research_ai:notebook_chat:stream:{execution_id}"


class ExecutionStreamStore:
    """Cache-backed preview shared by workers and REST processes."""

    def __init__(self, cache_backend=None):
        self._cache = cache if cache_backend is None else cache_backend

    def get(self, execution_id: int) -> dict | None:
        snapshot = self._cache.get(_cache_key(execution_id))
        return snapshot if isinstance(snapshot, dict) else None

    def set(self, execution_id: int, snapshot: dict) -> None:
        self._cache.set(
            _cache_key(execution_id),
            snapshot,
            timeout=STREAM_CACHE_TTL_SECONDS,
        )

    def clear(self, execution_id: int) -> None:
        self._cache.delete(_cache_key(execution_id))


class NotebookStreamBuffer:
    """Accumulate provider deltas, snapshot them, and publish small batches."""

    def __init__(
        self,
        *,
        conversation_id: int,
        execution_id: int,
        store: ExecutionStreamStore,
        publisher,
        is_active=None,
        clock=time.monotonic,
    ):
        self.conversation_id = conversation_id
        self.execution_id = execution_id
        self.store = store
        self.publisher = publisher
        self.is_active = is_active
        self.clock = clock
        self.iteration: int | None = None
        self.sequence = 0
        self.items: OrderedDict[str, dict] = OrderedDict()
        self.pending: OrderedDict[str, dict] = OrderedDict()
        self.pending_chars = 0
        self.last_flush_at: float | None = None
        self.last_active_check_at: float | None = None
        self.stream_revision = 0
        self.stopped = False

    def append(self, iteration: int, event) -> None:
        if self.stopped:
            return
        if isinstance(event, StreamReset):
            self.restart(iteration)
            return
        item_type, maximum = self._event_shape(event)
        if item_type is None:
            return
        if self.iteration != iteration:
            self.flush()
            self._reset(iteration)

        item_id = f"iteration-{iteration}:block-{event.block_index}:{item_type}"
        item = self.items.get(item_id)
        if item is None:
            item = {
                "id": item_id,
                "type": item_type,
                "text": "",
                "at": timezone.now().isoformat(),
            }
            self.items[item_id] = item

        room = maximum - len(item["text"])
        fragment = event.text[: max(0, room)]
        if not fragment:
            return
        item["text"] += fragment

        pending = self.pending.get(item_id)
        if pending is None:
            pending = {
                "id": item_id,
                "type": item_type,
                "delta": "",
                "at": item["at"],
            }
            self.pending[item_id] = pending
        pending["delta"] += fragment
        self.pending_chars += len(fragment)

        now = self.clock()
        if (
            self.last_flush_at is None
            or now - self.last_flush_at >= STREAM_FLUSH_INTERVAL_SECONDS
            or self.pending_chars >= STREAM_FLUSH_CHARS
        ):
            self.flush(now=now)

    def flush(self, *, now: float | None = None) -> None:
        if not self.pending or self.iteration is None:
            return
        now = self.clock() if now is None else now
        if self._active_check_due(now) and not self.is_active():
            self.disable()
            self.store.clear(self.execution_id)
            return

        sequence = self.sequence + 1
        stream_id = self._stream_id()
        deltas = [dict(delta) for delta in self.pending.values()]
        self.store.set(
            self.execution_id,
            {
                "id": stream_id,
                "sequence": sequence,
                "iteration": self.iteration,
                "items": [dict(item) for item in self.items.values()],
            },
        )
        self.publisher.publish_stream(
            self.conversation_id,
            self.execution_id,
            stream_id=stream_id,
            sequence=sequence,
            iteration=self.iteration,
            deltas=deltas,
        )
        self.sequence = sequence
        self.pending.clear()
        self.pending_chars = 0
        self.last_flush_at = now

    def restart(self, iteration: int) -> None:
        """Replace a discarded provider attempt with a new empty preview."""
        next_revision = self.stream_revision + 1 if self.iteration == iteration else 1
        self._reset(iteration)
        self.stream_revision = next_revision
        self.sequence = 1
        stream_id = self._stream_id()
        self.store.set(
            self.execution_id,
            {
                "id": stream_id,
                "sequence": self.sequence,
                "iteration": iteration,
                "items": [],
            },
        )
        self.publisher.publish_stream(
            self.conversation_id,
            self.execution_id,
            stream_id=stream_id,
            sequence=self.sequence,
            iteration=iteration,
            deltas=[],
        )
        self.last_flush_at = self.clock()

    def disable(self) -> None:
        """Drop local state and stop preview work for this provider turn."""
        self._reset(None)
        self.stopped = True

    def clear(self) -> None:
        self._reset(None)
        self.store.clear(self.execution_id)
        self.stopped = False

    def _reset(self, iteration: int | None) -> None:
        self.items.clear()
        self.pending.clear()
        self.pending_chars = 0
        self.iteration = iteration
        self.sequence = 0
        self.last_flush_at = None
        self.last_active_check_at = None
        self.stream_revision = 0

    def _active_check_due(self, now: float) -> bool:
        """Whether the throttled durable execution-state probe should run."""
        if self.is_active is None:
            return False
        if (
            self.last_active_check_at is not None
            and now - self.last_active_check_at < STREAM_ACTIVE_CHECK_INTERVAL_SECONDS
        ):
            return False
        self.last_active_check_at = now
        return True

    def _stream_id(self) -> str:
        stream_id = f"{self.execution_id}:{self.iteration}"
        if self.stream_revision:
            return f"{stream_id}:retry-{self.stream_revision}"
        return stream_id

    @staticmethod
    def _event_shape(event) -> tuple[str | None, int]:
        if isinstance(event, TextStreamDelta):
            return "narration", MAX_STREAM_TEXT_CHARS
        if isinstance(event, ThinkingStreamDelta):
            return "thinking", MAX_STREAM_THINKING_CHARS
        return None, 0
