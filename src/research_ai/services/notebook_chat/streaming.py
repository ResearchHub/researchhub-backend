"""Transient, reconnectable model-output streaming for notebook chat.

Completed provider turns still land in the agent context and trace as one
authoritative message. This module holds only the user-visible preview while a
turn is being emitted: small coalesced WebSocket deltas for the fast path and a
bounded cache checkpoint plus delta journal for reconnect/poll recovery.
"""

import logging
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager

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
STREAM_CHECKPOINT_INTERVAL_SECONDS = 1.0
STREAM_CHECKPOINT_CHARS = 4_096
# Execution ownership is database-backed; keep it far below the frame rate.
STREAM_ACTIVE_CHECK_INTERVAL_SECONDS = 1.0
STREAM_LOCK_TTL_SECONDS = 30
STREAM_LOCK_RENEW_INTERVAL_SECONDS = STREAM_LOCK_TTL_SECONDS / 3
# A publication that starts with a valid lease must finish before even one
# failed renewal could let the lease expire underneath it.
STREAM_PUBLISH_TIMEOUT_SECONDS = STREAM_LOCK_RENEW_INTERVAL_SECONDS / 2
STREAM_LOCK_WAIT_SECONDS = 2.0
STREAM_LOCK_POLL_SECONDS = 0.005
MAX_STREAM_TEXT_CHARS = 100_000
MAX_STREAM_THINKING_CHARS = 4_000

logger = logging.getLogger(__name__)


class _GuardLeaseRenewer:
    """Renew active Redis leases from one shared daemon thread per process."""

    def __init__(self, interval_seconds=STREAM_LOCK_RENEW_INTERVAL_SECONDS):
        self._interval_seconds = interval_seconds
        self._condition = threading.Condition()
        self._leases: set[object] = set()
        self._thread: threading.Thread | None = None

    def register(self, lease) -> None:
        with self._condition:
            self._leases.add(lease)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="notebook-stream-lock-renewer",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify()

    def unregister(self, lease) -> None:
        with self._condition:
            self._leases.discard(lease)
            self._condition.notify()

    def _run(self) -> None:
        while True:
            with self._condition:
                if not self._leases:
                    self._condition.wait()
                    continue
                renew_at = time.monotonic() + self._interval_seconds
                while self._leases and time.monotonic() < renew_at:
                    self._condition.wait(timeout=max(0, renew_at - time.monotonic()))
                if not self._leases:
                    continue
                for lease in tuple(self._leases):
                    try:
                        lease.renew()
                    except Exception:  # noqa: BLE001 - holder is invalidated
                        self._leases.discard(lease)
                        logger.warning(
                            "notebook chat stream lock renewal failed",
                            exc_info=True,
                        )


class _GuardLease:
    """Expose whether a Redis lease remained valid during guarded work."""

    def __init__(self, lease=None):
        self.lease = lease
        self._lost = threading.Event()

    def renew(self) -> None:
        try:
            renewed = self.lease.reacquire()
        except Exception:
            self._lost.set()
            raise
        if renewed is False:
            self._lost.set()
            raise StreamGuardLeaseLostError("stream guard lease is no longer owned")

    def ensure_valid(self) -> None:
        if self._lost.is_set():
            raise StreamGuardLeaseLostError("stream guard lease renewal failed")


_guard_lease_renewer = _GuardLeaseRenewer()


def _cache_key(execution_id: int) -> str:
    return f"research_ai:notebook_chat:stream:{execution_id}"


def _journal_cache_key(execution_id: int) -> str:
    return f"research_ai:notebook_chat:stream_journal:{execution_id}"


def _cancelled_cache_key(execution_id: int) -> str:
    return f"research_ai:notebook_chat:stream_cancelled:{execution_id}"


def _lock_cache_key(execution_id: int) -> str:
    return f"research_ai:notebook_chat:stream_lock:{execution_id}"


class StreamCacheUnavailableError(RuntimeError):
    """The optional stream cache could not be reached."""


class StreamGuardTimeoutError(RuntimeError):
    """A bounded stream operation could not obtain its execution guard."""


class StreamGuardLeaseLostError(StreamCacheUnavailableError):
    """A guarded operation can no longer prove that it owns its Redis lease."""


class ExecutionStreamStore:
    """Cache-backed recovery state shared by workers and REST processes."""

    def __init__(
        self,
        cache_backend=None,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self._cache = cache if cache_backend is None else cache_backend
        self._clock = clock
        self._sleep = sleep

    @contextmanager
    def guard(self, execution_id: int, *, wait_seconds=STREAM_LOCK_WAIT_SECONDS):
        """Serialize stream publication and cancellation across processes."""
        key = _lock_cache_key(execution_id)
        try:
            lease = self._redis_lock(key)
        except Exception as exc:
            raise StreamCacheUnavailableError from exc
        if lease is not None:
            try:
                acquired = lease.acquire(
                    blocking=True,
                    blocking_timeout=wait_seconds,
                )
            except Exception as exc:
                raise StreamCacheUnavailableError from exc
            if not acquired:
                raise StreamGuardTimeoutError(
                    f"timed out serializing stream {execution_id}"
                )
            guard = _GuardLease(lease)
            _guard_lease_renewer.register(guard)
            try:
                yield guard
            finally:
                # Unregister under the renewer's condition before releasing,
                # so it cannot revive a lease after the critical section.
                _guard_lease_renewer.unregister(guard)
                try:
                    lease.release()
                except Exception:  # noqa: BLE001 - lease expiry is fallback
                    logger.warning(
                        "notebook chat stream lock release failed (execution=%s)",
                        execution_id,
                        exc_info=True,
                    )
            return

        # Tests use a local-memory cache. A non-expiring local lease is safe
        # because no other process can inherit it; production Redis uses the
        # renewable, crash-expiring lease above.
        token = uuid.uuid4().hex
        deadline = None if wait_seconds is None else self._clock() + wait_seconds
        while True:
            try:
                acquired = self._cache.add(key, token, timeout=None)
            except Exception as exc:
                raise StreamCacheUnavailableError from exc
            if acquired:
                break
            if deadline is not None and self._clock() >= deadline:
                raise StreamGuardTimeoutError(
                    f"timed out serializing stream {execution_id}"
                )
            self._sleep(STREAM_LOCK_POLL_SECONDS)
        try:
            yield _GuardLease()
        finally:
            try:
                # The token prevents a stale owner from deleting a newer
                # lease if its own lock expired while it was suspended.
                if self._cache.get(key) == token:
                    self._cache.delete(key)
            except Exception:  # noqa: BLE001 - lock expiry is the fallback
                logger.warning(
                    "notebook chat stream lock release failed (execution=%s)",
                    execution_id,
                    exc_info=True,
                )

    def _redis_lock(self, key: str):
        """Build redis-py's token-safe lease for Django's RedisCache backend."""
        cache_client = getattr(self._cache, "_cache", None)
        get_client = getattr(cache_client, "get_client", None)
        make_key = getattr(self._cache, "make_key", None)
        if get_client is None or make_key is None:
            return None
        redis_key = make_key(key)
        client = get_client(redis_key, write=True)
        return client.lock(
            redis_key,
            timeout=STREAM_LOCK_TTL_SECONDS,
            sleep=STREAM_LOCK_POLL_SECONDS,
            thread_local=False,
        )

    def get(self, execution_id: int) -> dict | None:
        # Read the journal first. If a checkpoint lands between these reads,
        # its newer snapshot supersedes the older journal; the reverse order
        # could observe an old snapshot after that journal has been cleared.
        journal = self._cache.get(_journal_cache_key(execution_id))
        snapshot = self._cache.get(_cache_key(execution_id))
        if not isinstance(snapshot, dict):
            return None
        if not isinstance(journal, list):
            return snapshot
        return self._merge_journal(snapshot, journal)

    def set(self, execution_id: int, snapshot: dict) -> None:
        """Replace the full checkpoint and retire deltas it now contains."""
        self._cache.set(
            _cache_key(execution_id),
            snapshot,
            timeout=STREAM_CACHE_TTL_SECONDS,
        )
        self._cache.delete(_journal_cache_key(execution_id))

    def append_deltas(
        self,
        execution_id: int,
        *,
        stream_id: str,
        sequence: int,
        deltas: list[dict],
    ) -> None:
        """Retain one published batch without rewriting the full checkpoint."""
        key = _journal_cache_key(execution_id)
        journal = self._cache.get(key)
        if not isinstance(journal, list):
            journal = []
        journal = [
            entry
            for entry in journal
            if isinstance(entry, dict)
            and entry.get("id") == stream_id
            and isinstance(entry.get("sequence"), int)
            and entry["sequence"] < sequence
        ]
        journal.append(
            {
                "id": stream_id,
                "sequence": sequence,
                "deltas": [dict(delta) for delta in deltas],
            }
        )
        self._cache.set(key, journal, timeout=STREAM_CACHE_TTL_SECONDS)

    def clear(self, execution_id: int) -> None:
        try:
            self._cache.delete(_cache_key(execution_id))
        finally:
            self._cache.delete(_journal_cache_key(execution_id))

    def cancel(self, execution_id: int) -> None:
        """Mark a stream cancelled before removing its reconnect snapshot."""
        try:
            self._cache.set(
                _cancelled_cache_key(execution_id),
                True,
                timeout=STREAM_CACHE_TTL_SECONDS,
            )
        finally:
            self.clear(execution_id)

    def is_cancelled(self, execution_id: int) -> bool:
        """Return the cheap, cache-backed cancellation signal for a worker."""
        return self._cache.get(_cancelled_cache_key(execution_id)) is True

    @staticmethod
    def _merge_journal(snapshot: dict, journal: list) -> dict:
        """Apply contiguous batches newer than ``snapshot`` to a safe copy."""
        stream_id = snapshot.get("id")
        sequence = snapshot.get("sequence")
        items = snapshot.get("items")
        if not isinstance(stream_id, str) or not isinstance(sequence, int):
            return snapshot
        if not isinstance(items, list) or not all(
            isinstance(item, dict) for item in items
        ):
            return snapshot

        recovered = dict(snapshot)
        recovered_items = [dict(item) for item in items]
        recovered["items"] = recovered_items
        items_by_id = {
            item.get("id"): item
            for item in recovered_items
            if isinstance(item.get("id"), str)
        }

        for batch in journal:
            if not isinstance(batch, dict) or batch.get("id") != stream_id:
                continue
            batch_sequence = batch.get("sequence")
            if not isinstance(batch_sequence, int) or batch_sequence <= sequence:
                continue
            if batch_sequence != sequence + 1:
                break
            deltas = batch.get("deltas")
            if not isinstance(deltas, list):
                break
            for delta in deltas:
                if not isinstance(delta, dict):
                    continue
                item_id = delta.get("id")
                fragment = delta.get("delta")
                if not isinstance(item_id, str) or not isinstance(fragment, str):
                    continue
                item = items_by_id.get(item_id)
                if item is None:
                    item = {
                        "id": item_id,
                        "type": delta.get("type"),
                        "text": "",
                        "at": delta.get("at"),
                    }
                    recovered_items.append(item)
                    items_by_id[item_id] = item
                item["text"] += fragment
            sequence = batch_sequence
            recovered["sequence"] = sequence
        return recovered


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
        self.uncheckpointed_chars = 0
        self.last_flush_at: float | None = None
        self.last_checkpoint_at: float | None = None
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
        self.uncheckpointed_chars += len(fragment)

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
            self._reset(None)
            self.stopped = True
            return
        checkpoint = self._checkpoint_due(now)
        with self.store.guard(self.execution_id) as guard:
            if self.store.is_cancelled(self.execution_id):
                # Cancellation clears the shared snapshot. Drop this worker's
                # buffered copy so an in-flight provider cannot recreate it or
                # publish deltas after the authoritative turn_cancelled event.
                self._reset(None)
                self.stopped = True
                return
            sequence = self.sequence + 1
            stream_id = self._stream_id()
            deltas = [dict(delta) for delta in self.pending.values()]

            if checkpoint:
                self.store.set(
                    self.execution_id,
                    {
                        "id": stream_id,
                        "sequence": sequence,
                        "iteration": self.iteration,
                        "items": [dict(item) for item in self.items.values()],
                    },
                )
            else:
                self.store.append_deltas(
                    self.execution_id,
                    stream_id=stream_id,
                    sequence=sequence,
                    deltas=deltas,
                )
            # A renewal failure permanently invalidates this critical section,
            # even if Redis has since recovered. Do not publish under a lease
            # that another process may now own.
            guard.ensure_valid()
            # Keep socket publication under the same renewable cross-process
            # guard as cancellation. Full recovery snapshots are checkpointed
            # less often than the small WebSocket batches; the bounded delta
            # journal keeps every published sequence recoverable without
            # rewriting all accumulated text at frame rate.
            self.publisher.publish_stream(
                self.conversation_id,
                self.execution_id,
                stream_id=stream_id,
                sequence=sequence,
                iteration=self.iteration,
                deltas=deltas,
            )
            guard.ensure_valid()
            self.sequence = sequence
        self.pending.clear()
        self.pending_chars = 0
        self.last_flush_at = now
        if checkpoint:
            self.uncheckpointed_chars = 0
            self.last_checkpoint_at = now

    def restart(self, iteration: int) -> None:
        """Replace a discarded provider attempt with a new empty preview."""
        next_revision = self.stream_revision + 1 if self.iteration == iteration else 1
        now = self.clock()
        with self.store.guard(self.execution_id) as guard:
            if self.store.is_cancelled(self.execution_id):
                self.disable()
                return
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
            guard.ensure_valid()
            self.publisher.publish_stream(
                self.conversation_id,
                self.execution_id,
                stream_id=stream_id,
                sequence=self.sequence,
                iteration=iteration,
                deltas=[],
            )
            guard.ensure_valid()
        self.last_checkpoint_at = now

    def disable(self) -> None:
        """Drop local state and fail closed for the rest of this model turn."""
        self._reset(None)
        self.stopped = True

    def clear(self) -> None:
        self.pending.clear()
        self.pending_chars = 0
        self.uncheckpointed_chars = 0
        self.items.clear()
        self.store.clear(self.execution_id)
        self.iteration = None
        self.sequence = 0
        self.last_flush_at = None
        self.last_checkpoint_at = None
        self.last_active_check_at = None
        self.stream_revision = 0
        self.stopped = False

    def _reset(self, iteration: int | None) -> None:
        self.items.clear()
        self.pending.clear()
        self.pending_chars = 0
        self.uncheckpointed_chars = 0
        self.iteration = iteration
        self.sequence = 0
        self.last_flush_at = None
        self.last_checkpoint_at = None
        self.last_active_check_at = None
        self.stream_revision = 0

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

    def _checkpoint_due(self, now: float) -> bool:
        return (
            self.last_checkpoint_at is None
            or now - self.last_checkpoint_at >= STREAM_CHECKPOINT_INTERVAL_SECONDS
            or self.uncheckpointed_chars >= STREAM_CHECKPOINT_CHARS
        )

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
