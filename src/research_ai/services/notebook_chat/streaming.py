"""Transient, reconnectable model-output streaming for notebook chat.

Completed provider turns still land in the agent context and trace as one
authoritative message. This module holds only the user-visible preview while a
turn is being emitted: small coalesced WebSocket deltas for the fast path and a
bounded cache snapshot for reconnect/poll recovery.
"""

import time
from collections import OrderedDict

from django.core.cache import cache
from django.utils import timezone

from research_ai.services.agent.types import TextStreamDelta, ThinkingStreamDelta

STREAM_DELTA = "stream_delta"
STREAM_CACHE_TTL_SECONDS = 60 * 60
STREAM_FLUSH_INTERVAL_SECONDS = 0.075
STREAM_FLUSH_CHARS = 512
# Execution ownership is database-backed; keep it far below the frame rate.
STREAM_ACTIVE_CHECK_INTERVAL_SECONDS = 1.0
MAX_STREAM_TEXT_CHARS = 100_000
MAX_STREAM_THINKING_CHARS = 4_000


def _cache_key(execution_id: int) -> str:
    return f"research_ai:notebook_chat:stream:{execution_id}"


class ExecutionStreamStore:
    """Cache-backed snapshot store shared by workers and REST processes."""

    def __init__(self, cache_backend=None):
        self._cache = cache if cache_backend is None else cache_backend

    def get(self, execution_id: int) -> dict | None:
        value = self._cache.get(_cache_key(execution_id))
        return value if isinstance(value, dict) else None

    def set(self, execution_id: int, snapshot: dict) -> None:
        self._cache.set(
            _cache_key(execution_id),
            snapshot,
            timeout=STREAM_CACHE_TTL_SECONDS,
        )

    def clear(self, execution_id: int) -> None:
        self._cache.delete(_cache_key(execution_id))


class NotebookStreamBuffer:
    """Accumulate provider deltas, checkpoint them, and publish small batches."""

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
        self.stopped = False

    def append(self, iteration: int, event) -> None:
        if self.stopped:
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
            # Cancellation clears the shared snapshot. Drop this worker's
            # buffered copy so an in-flight provider cannot recreate it or
            # publish deltas after the authoritative turn_cancelled event.
            self._reset(None)
            self.stopped = True
            return
        self.sequence += 1
        stream_id = self._stream_id()
        snapshot = {
            "id": stream_id,
            "sequence": self.sequence,
            "iteration": self.iteration,
            "items": [dict(item) for item in self.items.values()],
        }
        deltas = [dict(delta) for delta in self.pending.values()]

        # The snapshot lands first: a socket event can trigger an immediate
        # fallback refetch, which must never observe an older stream revision.
        self.store.set(self.execution_id, snapshot)
        self.publisher.publish_stream(
            self.conversation_id,
            self.execution_id,
            stream_id=stream_id,
            sequence=self.sequence,
            iteration=self.iteration,
            deltas=deltas,
        )
        self.pending.clear()
        self.pending_chars = 0
        self.last_flush_at = now

    def clear(self) -> None:
        self.pending.clear()
        self.pending_chars = 0
        self.items.clear()
        self.store.clear(self.execution_id)
        self.iteration = None
        self.sequence = 0
        self.last_flush_at = None
        self.last_active_check_at = None
        self.stopped = False

    def _reset(self, iteration: int | None) -> None:
        self.items.clear()
        self.pending.clear()
        self.pending_chars = 0
        self.iteration = iteration
        self.sequence = 0
        self.last_flush_at = None
        self.last_active_check_at = None

    def _active_check_due(self, now: float) -> bool:
        """Whether the throttled execution-ownership probe should run now."""
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
        return f"{self.execution_id}:{self.iteration}"

    @staticmethod
    def _event_shape(event) -> tuple[str | None, int]:
        if isinstance(event, TextStreamDelta):
            return "narration", MAX_STREAM_TEXT_CHARS
        if isinstance(event, ThinkingStreamDelta):
            return "thinking", MAX_STREAM_THINKING_CHARS
        return None, 0
