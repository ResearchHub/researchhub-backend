"""Transient, reconnectable model-output streaming for notebook chat.

Completed provider turns still land in the agent context and trace as one
authoritative message. This module holds only a bounded user-visible preview:
small coalesced WebSocket deltas for the fast path and one cache snapshot for
reconnect and polling recovery.

Three item kinds share the preview: ``narration`` (answer text), ``thinking``
(readable reasoning) and ``tool_draft`` -- a tool call the model is composing.
Draft items carry the tool name and a label from the moment the block opens,
so the client can say what the model is doing during the long stretches where
every output token is a tool argument; for tools whose arguments are note
prose (``edit_note``) the text being written streams into the item as well.

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
    ToolInputStreamDelta,
    ToolUseStreamStart,
)
from research_ai.services.notebook_chat.activity import drafting_label
from research_ai.services.notebook_chat.tool_draft import (
    TOOL_DRAFT_PROSE_TOOLS,
    ToolDraftTextExtractor,
)

STREAM_DELTA = "stream_delta"
STREAM_CACHE_TTL_SECONDS = 60 * 60
STREAM_FLUSH_INTERVAL_SECONDS = 0.075
STREAM_FLUSH_CHARS = 512
STREAM_ACTIVE_CHECK_INTERVAL_SECONDS = 1.0
STREAM_PUBLISH_TIMEOUT_SECONDS = 5.0
MAX_STREAM_TEXT_CHARS = 100_000
MAX_STREAM_THINKING_CHARS = 4_000
# A drafted edit is the prose of the blocks being rewritten -- a few
# paragraphs in practice; the bound only stops a runaway call from growing
# the per-flush snapshot without limit.
MAX_STREAM_TOOL_DRAFT_CHARS = 20_000

ITEM_NARRATION = "narration"
ITEM_THINKING = "thinking"
ITEM_TOOL_DRAFT = "tool_draft"


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
        # Per draft item, the scanner turning argument JSON into prose.
        self.drafts: dict[str, ToolDraftTextExtractor] = {}
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
        opened = item is None
        if item is None:
            item = self._new_item(item_id, item_type, event)
            self.items[item_id] = item

        room = maximum - len(item["text"])
        fragment = self._fragment(item, event)[: max(0, room)]
        # A tool-use start carries no text but must still announce its item;
        # anything else with nothing to show is a no-op.
        announces = opened and isinstance(event, ToolUseStreamStart)
        if not fragment and not announces:
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
            if item_type == ITEM_TOOL_DRAFT:
                pending["tool"] = item["tool"]
                pending["label"] = item["label"]
            self.pending[item_id] = pending
        pending["delta"] += fragment
        self.pending_chars += len(fragment)

        now = self.clock()
        if (
            # A draft announcement must not wait out the coalescing window:
            # a server-side tool can follow it with seconds of silence.
            announces
            or self.last_flush_at is None
            or now - self.last_flush_at >= STREAM_FLUSH_INTERVAL_SECONDS
            or self.pending_chars >= STREAM_FLUSH_CHARS
        ):
            self.flush(now=now)

    def _new_item(self, item_id: str, item_type: str, event) -> dict:
        item = {
            "id": item_id,
            "type": item_type,
            "text": "",
            "at": timezone.now().isoformat(),
        }
        if item_type == ITEM_TOOL_DRAFT:
            # An argument delta without its start event (not expected from
            # the provider) still gets an item, just an unnamed one.
            tool = event.name if isinstance(event, ToolUseStreamStart) else ""
            item["tool"] = tool
            item["label"] = drafting_label(tool)
            if tool in TOOL_DRAFT_PROSE_TOOLS:
                self.drafts[item_id] = ToolDraftTextExtractor()
        return item

    def _fragment(self, item: dict, event) -> str:
        """The user-visible text ``event`` adds to ``item``."""
        if isinstance(event, ToolUseStreamStart):
            return ""
        if isinstance(event, ToolInputStreamDelta):
            extractor = self.drafts.get(item["id"])
            return extractor.feed(event.partial_json) if extractor else ""
        return event.text

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
        published = self.publisher.publish_stream(
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
        if published is False:
            # Channel delivery is optional, but retrying a stalled send for
            # every provider chunk can block consumption of the model stream.
            # Keep the last recovery snapshot and stop preview work this turn.
            self.disable()

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
        published = self.publisher.publish_stream(
            self.conversation_id,
            self.execution_id,
            stream_id=stream_id,
            sequence=self.sequence,
            iteration=iteration,
            deltas=[],
        )
        self.last_flush_at = self.clock()
        if published is False:
            self.disable()

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
        self.drafts.clear()
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
            return ITEM_NARRATION, MAX_STREAM_TEXT_CHARS
        if isinstance(event, ThinkingStreamDelta):
            return ITEM_THINKING, MAX_STREAM_THINKING_CHARS
        if isinstance(event, ToolUseStreamStart | ToolInputStreamDelta):
            return ITEM_TOOL_DRAFT, MAX_STREAM_TOOL_DRAFT_CHARS
        return None, 0
