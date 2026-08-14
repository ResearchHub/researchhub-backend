import threading
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from research_ai.services.agent.types import TextStreamDelta, ThinkingStreamDelta
from research_ai.services.notebook_chat import streaming
from research_ai.services.notebook_chat.streaming import (
    MAX_STREAM_THINKING_CHARS,
    STREAM_CHECKPOINT_CHARS,
    STREAM_LOCK_TTL_SECONDS,
    ExecutionStreamStore,
    NotebookStreamBuffer,
    StreamCacheUnavailableError,
    StreamGuardTimeoutError,
)


class FakeCache:
    def __init__(self):
        self.values = {}
        self.set_calls = []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        self.set_calls.append((key, value, timeout))
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)

    def add(self, key, value, timeout=None):
        if key in self.values:
            return False
        self.values[key] = value
        return True


class FakePublisher:
    def __init__(self):
        self.calls = []

    def publish_stream(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class NotebookStreamBufferTests(SimpleTestCase):
    def setUp(self):
        self.now = 10.0
        self.cache = FakeCache()
        self.store = ExecutionStreamStore(cache_backend=self.cache)
        self.publisher = FakePublisher()
        self.buffer = NotebookStreamBuffer(
            conversation_id=7,
            execution_id=9,
            store=self.store,
            publisher=self.publisher,
            clock=lambda: self.now,
        )

    def test_first_delta_publishes_and_checkpoints_a_reconnect_snapshot(self):
        # Arrange
        event = TextStreamDelta(block_index=1, text="hel")

        # Act
        self.buffer.append(2, event)

        # Assert
        snapshot = self.store.get(9)
        self.assertEqual(snapshot["id"], "9:2")
        self.assertEqual(snapshot["sequence"], 1)
        self.assertEqual(
            snapshot["items"][0],
            {
                "id": "iteration-2:block-1:narration",
                "type": "narration",
                "text": "hel",
                "at": snapshot["items"][0]["at"],
            },
        )
        self.assertEqual(
            self.publisher.calls[0][1]["deltas"],
            [
                {
                    "id": "iteration-2:block-1:narration",
                    "type": "narration",
                    "delta": "hel",
                    "at": snapshot["items"][0]["at"],
                }
            ],
        )

    def test_later_fragments_coalesce_until_flush(self):
        # Arrange
        self.buffer.append(1, TextStreamDelta(block_index=0, text="a"))
        self.now += 0.01

        # Act
        self.buffer.append(1, TextStreamDelta(block_index=0, text="b"))
        self.buffer.append(1, TextStreamDelta(block_index=0, text="c"))
        self.buffer.flush()

        # Assert
        self.assertEqual(len(self.publisher.calls), 2)
        self.assertEqual(self.publisher.calls[-1][1]["deltas"][0]["delta"], "bc")
        self.assertEqual(self.store.get(9)["items"][0]["text"], "a")
        self.assertEqual(self.store.get(9)["sequence"], 1)

    def test_full_snapshot_is_checkpointed_less_often_than_socket_deltas(self):
        # Arrange
        self.buffer.append(1, TextStreamDelta(block_index=0, text="a"))
        for fragment in "bcdef":
            self.now += 0.08
            self.buffer.append(1, TextStreamDelta(block_index=0, text=fragment))

        # Act
        snapshot_before_interval = self.store.get(9)
        self.now += 1
        self.buffer.append(1, TextStreamDelta(block_index=0, text="g"))

        # Assert
        self.assertEqual(len(self.publisher.calls), 7)
        self.assertEqual(len(self.cache.set_calls), 2)
        self.assertEqual(snapshot_before_interval["items"][0]["text"], "a")
        self.assertEqual(self.store.get(9)["items"][0]["text"], "abcdefg")

    def test_full_snapshot_checkpoints_after_enough_new_text(self):
        # Arrange
        self.buffer.append(1, TextStreamDelta(block_index=0, text="a"))
        fragment = "x" * 512

        # Act
        for _ in range(STREAM_CHECKPOINT_CHARS // len(fragment)):
            self.now += 0.01
            self.buffer.append(1, TextStreamDelta(block_index=0, text=fragment))

        # Assert
        self.assertEqual(len(self.cache.set_calls), 2)
        self.assertEqual(
            len(self.store.get(9)["items"][0]["text"]),
            STREAM_CHECKPOINT_CHARS + 1,
        )

    def test_thinking_preview_is_bounded_and_opaque_state_is_not_accepted(self):
        # Arrange
        oversized = "x" * (MAX_STREAM_THINKING_CHARS + 10)

        # Act
        self.buffer.append(1, ThinkingStreamDelta(block_index=0, text=oversized))
        self.buffer.append(1, object())

        # Assert
        item = self.store.get(9)["items"][0]
        self.assertEqual(item["type"], "thinking")
        self.assertEqual(len(item["text"]), MAX_STREAM_THINKING_CHARS)
        self.assertEqual(len(self.publisher.calls), 1)

    def test_clear_removes_the_reconnect_snapshot(self):
        # Arrange
        self.buffer.append(1, TextStreamDelta(block_index=0, text="hello"))
        self.assertIsNotNone(self.store.get(9))

        # Act
        self.buffer.clear()

        # Assert
        self.assertIsNone(self.store.get(9))

    def test_bounded_stream_guard_times_out_under_contention(self):
        # Arrange, Act & Assert
        with (
            self.store.guard(9),
            self.assertRaises(StreamGuardTimeoutError),
            self.store.guard(9, wait_seconds=0),
        ):
            self.fail("contended guard should not be entered")

    def test_redis_stream_guard_renews_while_critical_section_is_running(self):
        # Arrange
        renewed = threading.Event()
        lease = Mock()
        lease.acquire.return_value = True
        lease.reacquire.side_effect = renewed.set
        renewer = streaming._GuardLeaseRenewer(interval_seconds=0.01)
        store = ExecutionStreamStore(cache_backend=self.cache)

        # Act
        with (
            patch.object(streaming, "_guard_lease_renewer", renewer),
            patch.object(store, "_redis_lock", return_value=lease),
            store.guard(9),
        ):
            self.assertTrue(renewed.wait(timeout=0.2))

        # Assert
        lease.acquire.assert_called_once_with(
            blocking=True,
            blocking_timeout=2.0,
        )
        lease.reacquire.assert_called()
        lease.release.assert_called_once_with()

    def test_redis_stream_guard_uses_token_safe_expiring_lock(self):
        # Arrange
        redis_cache = Mock()
        redis_cache.make_key.return_value = "prefixed-lock-key"
        redis_client = redis_cache._cache.get_client.return_value
        lease = redis_client.lock.return_value
        lease.acquire.return_value = True
        store = ExecutionStreamStore(cache_backend=redis_cache)

        # Act
        with store.guard(9, wait_seconds=0):
            pass

        # Assert
        redis_cache._cache.get_client.assert_called_once_with(
            "prefixed-lock-key",
            write=True,
        )
        redis_client.lock.assert_called_once_with(
            "prefixed-lock-key",
            timeout=STREAM_LOCK_TTL_SECONDS,
            sleep=0.005,
            thread_local=False,
        )
        lease.acquire.assert_called_once_with(blocking=True, blocking_timeout=0)
        lease.release.assert_called_once_with()

    def test_redis_stream_guard_reports_cache_failure(self):
        # Arrange
        lease = Mock()
        lease.acquire.side_effect = ConnectionError("redis unavailable")

        # Act & Assert
        with (
            patch.object(self.store, "_redis_lock", return_value=lease),
            self.assertRaises(StreamCacheUnavailableError),
            self.store.guard(9),
        ):
            self.fail("unavailable guard should not be entered")

    def test_cancellation_marker_stops_deltas_while_activity_checks_are_throttled(self):
        # Arrange
        is_active = Mock(return_value=True)
        buffer = NotebookStreamBuffer(
            conversation_id=7,
            execution_id=9,
            store=self.store,
            publisher=self.publisher,
            is_active=is_active,
            clock=lambda: self.now,
        )
        buffer.append(1, TextStreamDelta(block_index=0, text="before"))
        self.now += 0.1
        buffer.append(1, TextStreamDelta(block_index=0, text="middle"))
        self.store.cancel(9)
        is_active.return_value = False
        self.now += 0.1

        # Act
        buffer.append(1, TextStreamDelta(block_index=0, text="after"))
        buffer.append(1, TextStreamDelta(block_index=0, text="later"))

        # Assert: the cache marker is checked for every batch and stops output
        # immediately, while database ownership remains throttled.
        self.assertIsNone(self.store.get(9))
        self.assertEqual(len(self.publisher.calls), 2)
        self.assertEqual(is_active.call_count, 1)

    def test_cancellation_waits_for_an_inflight_stream_publication(self):
        # Arrange
        publish_started = threading.Event()
        release_publish = threading.Event()
        cancellation_started = threading.Event()
        cancellation_finished = threading.Event()
        order = []

        def publish_stream(*args, **kwargs):
            order.append("stream_delta")
            publish_started.set()
            release_publish.wait(timeout=1)

        self.publisher.publish_stream = publish_stream
        publish_thread = threading.Thread(
            target=self.buffer.append,
            args=(1, TextStreamDelta(block_index=0, text="before")),
        )

        def cancel_stream():
            cancellation_started.set()
            with self.store.guard(9):
                self.store.cancel(9)
                order.append("turn_cancelled")
            cancellation_finished.set()

        # Act
        publish_thread.start()
        self.assertTrue(publish_started.wait(timeout=1))
        cancel_thread = threading.Thread(target=cancel_stream)
        cancel_thread.start()
        self.assertTrue(cancellation_started.wait(timeout=1))
        self.assertFalse(cancellation_finished.wait(timeout=0.05))
        release_publish.set()
        publish_thread.join(timeout=1)
        cancel_thread.join(timeout=1)

        # Assert: cancellation cannot become visible until the earlier delta
        # finishes, and its marker prevents every later delta.
        self.assertFalse(publish_thread.is_alive())
        self.assertFalse(cancel_thread.is_alive())
        self.now += 0.1
        self.buffer.append(1, TextStreamDelta(block_index=0, text="after"))
        self.assertEqual(order, ["stream_delta", "turn_cancelled"])
        self.assertTrue(cancellation_finished.is_set())
        self.assertIsNone(self.store.get(9))
