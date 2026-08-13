from unittest.mock import Mock

from django.test import SimpleTestCase

from research_ai.services.agent.types import TextStreamDelta, ThinkingStreamDelta
from research_ai.services.notebook_chat.streaming import (
    MAX_STREAM_THINKING_CHARS,
    STREAM_ACTIVE_CHECK_INTERVAL_SECONDS,
    ExecutionStreamStore,
    NotebookStreamBuffer,
)


class FakeCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, timeout=None):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


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
        self.assertEqual(self.store.get(9)["items"][0]["text"], "abc")
        self.assertEqual(self.store.get(9)["sequence"], 2)

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

    def test_activity_checks_are_throttled_and_cancellation_stops_deltas(self):
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
        self.store.clear(9)  # cancel_active_turn clears the shared snapshot
        is_active.return_value = False
        self.now += STREAM_ACTIVE_CHECK_INTERVAL_SECONDS

        # Act
        buffer.append(1, TextStreamDelta(block_index=0, text="after"))
        buffer.append(1, TextStreamDelta(block_index=0, text="later"))

        # Assert: batches poll execution ownership at most once per interval,
        # then stop permanently after observing cancellation.
        self.assertIsNone(self.store.get(9))
        self.assertEqual(len(self.publisher.calls), 2)
        self.assertEqual(is_active.call_count, 2)
