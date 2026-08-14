import unittest
from unittest.mock import Mock

from django.test import TestCase

from research_ai.services.agent.types import TextStreamDelta
from research_ai.services.notebook_chat.events import (
    EVENT_TYPE,
    TURN_FAILED,
    TURN_FINISHED,
    TURN_PROGRESS,
    ConversationEventPublisher,
    PublishingRecorder,
    conversation_group,
)
from research_ai.services.notebook_chat.streaming import STREAM_DELTA


class FakeChannelLayer:
    """Records group_send calls; optionally fails like a down Redis."""

    def __init__(self, error: Exception | None = None):
        self.sent = []
        self._error = error

    async def group_send(self, group, message):
        if self._error is not None:
            raise self._error
        self.sent.append((group, message))


class ConversationEventPublisherTests(TestCase):
    def test_publish_sends_to_the_conversation_group_after_commit(self):
        # Arrange
        layer = FakeChannelLayer()
        publisher = ConversationEventPublisher(channel_layer=layer)

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            publisher.publish(12, 34, TURN_PROGRESS)
            # Deferred: nothing may be pushed before the transaction commits,
            # or a nudged refetch could read state that is not visible yet.
            self.assertEqual(layer.sent, [])

        # Assert
        self.assertEqual(
            layer.sent,
            [
                (
                    conversation_group(12),
                    {
                        "type": EVENT_TYPE,
                        "data": {
                            "conversation_id": 12,
                            "execution_id": 34,
                            "kind": TURN_PROGRESS,
                        },
                    },
                )
            ],
        )

    def test_publish_survives_a_failing_channel_layer(self):
        # Arrange
        layer = FakeChannelLayer(error=RuntimeError("redis down"))
        publisher = ConversationEventPublisher(channel_layer=layer)

        # Act & Assert: the failure is logged, never raised into the caller.
        with (
            self.assertLogs(
                "research_ai.services.notebook_chat.events", level="WARNING"
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            publisher.publish(12, 34, TURN_FINISHED)

    def test_publish_stream_forwards_delta_payload_immediately(self):
        # Arrange
        layer = FakeChannelLayer()
        publisher = ConversationEventPublisher(channel_layer=layer)

        # Act
        publisher.publish_stream(
            12,
            34,
            stream_id="34:1",
            sequence=2,
            iteration=1,
            deltas=[
                {
                    "id": "block",
                    "type": "narration",
                    "delta": "hi",
                    "at": "2026-08-13T12:00:00Z",
                }
            ],
        )

        # Assert
        self.assertEqual(
            layer.sent[0][1]["data"],
            {
                "conversation_id": 12,
                "execution_id": 34,
                "kind": STREAM_DELTA,
                "stream_id": "34:1",
                "sequence": 2,
                "iteration": 1,
                "deltas": [
                    {
                        "id": "block",
                        "type": "narration",
                        "delta": "hi",
                        "at": "2026-08-13T12:00:00Z",
                    }
                ],
            },
        )


class PublishingRecorderTests(unittest.TestCase):
    """Pure delegation tests; no Django machinery involved."""

    def setUp(self):
        self.wrapped = Mock()
        self.wrapped.is_active.return_value = True
        self.publisher = Mock()
        self.stream_store = Mock()
        self.stream_store.is_cancelled.return_value = False
        self.recorder = PublishingRecorder(
            self.wrapped,
            self.publisher,
            conversation_id=7,
            execution_id=9,
            stream_store=self.stream_store,
        )

    def test_record_message_forwards_then_publishes_progress(self):
        # Arrange
        message, turn = object(), object()

        # Act
        self.recorder.record_message(message, turn=turn)

        # Assert
        self.wrapped.record_message.assert_called_once_with(message, turn=turn)
        self.publisher.publish.assert_called_once_with(7, 9, TURN_PROGRESS)

    def test_terminal_hooks_forward_then_publish(self):
        # Arrange: the wrapped recorder reports that each hook performed its
        # terminal transition itself.
        self.wrapped.on_run_finished.return_value = True
        self.wrapped.on_run_failed.return_value = True
        result, error = object(), RuntimeError("boom")

        # Act
        self.recorder.on_run_finished(result)
        self.recorder.on_run_failed(error)

        # Assert
        self.wrapped.on_run_finished.assert_called_once_with(result)
        self.wrapped.on_run_failed.assert_called_once_with(error)
        self.assertEqual(
            [call.args for call in self.publisher.publish.call_args_list],
            [(7, 9, TURN_FINISHED), (7, 9, TURN_FAILED)],
        )

    def test_stream_event_is_checkpointed_and_published(self):
        # Arrange
        event = TextStreamDelta(block_index=0, text="hello")

        # Act
        self.recorder.record_stream_event(1, event)

        # Assert
        self.stream_store.set.assert_called_once()
        self.publisher.publish_stream.assert_called_once()
        self.assertEqual(
            self.publisher.publish_stream.call_args.kwargs["deltas"][0]["delta"],
            "hello",
        )

    def test_stream_cache_failures_do_not_interrupt_durable_recording(self):
        # Arrange: the first failed checkpoint leaves a pending preview, so
        # record_message retries both the flush and the subsequent clear.
        self.stream_store.set.side_effect = RuntimeError("redis down")
        self.stream_store.clear.side_effect = RuntimeError("redis down")
        message, turn = object(), object()

        # Act
        with self.assertLogs(
            "research_ai.services.notebook_chat.events", level="WARNING"
        ):
            self.recorder.record_stream_event(
                1, TextStreamDelta(block_index=0, text="hello")
            )
            self.recorder.record_message(message, turn=turn)

        # Assert: only the transient preview was lost. The authoritative
        # message and its durable progress notification still landed.
        self.wrapped.record_message.assert_called_once_with(message, turn=turn)
        self.publisher.publish.assert_called_once_with(7, 9, TURN_PROGRESS)

    def test_inactive_execution_drops_stream_events(self):
        # Arrange
        self.wrapped.is_active.return_value = False

        # Act
        self.recorder.record_stream_event(
            1, TextStreamDelta(block_index=0, text="too late")
        )

        # Assert
        self.stream_store.set.assert_not_called()
        self.publisher.publish_stream.assert_not_called()

    def test_terminal_hooks_that_did_not_transition_publish_nothing(self):
        # Arrange: each hook finds the execution already sealed from outside
        # (cancelled) and reports performing no transition of its own.
        self.wrapped.on_run_finished.return_value = False
        self.wrapped.on_run_failed.return_value = False

        # Act
        self.recorder.on_run_finished(object())
        self.recorder.on_run_failed(InterruptedError("no longer running"))

        # Assert: forwarded for persistence, but no contradictory event on
        # top of the turn_cancelled the subscribers already received.
        self.wrapped.on_run_finished.assert_called_once()
        self.wrapped.on_run_failed.assert_called_once()
        self.publisher.publish.assert_not_called()

    def test_a_refused_write_publishes_nothing(self):
        # Arrange: the run was cancelled, so the durable write is refused.
        self.wrapped.record_message.side_effect = InterruptedError("cancelled")

        # Act & Assert: the exception propagates and no event narrates a
        # write that never landed.
        with self.assertRaises(InterruptedError):
            self.recorder.record_message(object())
        self.publisher.publish.assert_not_called()

    def test_everything_else_is_delegated_to_the_wrapped_recorder(self):
        # Arrange
        self.wrapped.is_active.return_value = False
        self.wrapped.terminal_observed = True
        self.wrapped.requires_durable_messages = True

        # Act & Assert: the loop's optional-contract lookups reach the
        # wrapped recorder untouched.
        self.assertFalse(self.recorder.is_active())
        self.assertTrue(self.recorder.terminal_observed)
        self.assertTrue(self.recorder.requires_durable_messages)
        self.publisher.publish.assert_not_called()
