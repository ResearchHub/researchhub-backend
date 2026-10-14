"""Unit tests for Expert Finder WebSocket event publishing."""

from django.test import TestCase

from research_ai.services.expert_finder.events import (
    EVENT_TYPE,
    EXPERTS_FOUND,
    SEARCH_FAILED,
    SEARCH_FINISHED,
    SEARCH_PROGRESS,
    ExpertFinderEventPublisher,
    search_group,
)


class FakeChannelLayer:
    """Records group_send calls; optionally fails like a down Redis."""

    def __init__(self, error: Exception | None = None):
        self.sent = []
        self._error = error

    async def group_send(self, group, message):
        if self._error is not None:
            raise self._error
        self.sent.append((group, message))


class ExpertFinderEventPublisherTests(TestCase):
    def test_search_group_normalizes_id(self):
        self.assertEqual(search_group("12"), "expert_finder_search_12")
        self.assertEqual(search_group(12), "expert_finder_search_12")

    def test_publish_progress_sends_after_commit(self):
        # Arrange
        layer = FakeChannelLayer()
        publisher = ExpertFinderEventPublisher(channel_layer=layer)

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            publisher.publish_progress(
                12,
                status="processing",
                progress=28,
                current_step="Finding experts...",
            )
            self.assertEqual(layer.sent, [])

        # Assert
        self.assertEqual(
            layer.sent,
            [
                (
                    search_group(12),
                    {
                        "type": EVENT_TYPE,
                        "data": {
                            "search_id": 12,
                            "kind": SEARCH_PROGRESS,
                            "status": "processing",
                            "progress": 28,
                            "current_step": "Finding experts...",
                        },
                    },
                )
            ],
        )

    def test_publish_experts_found(self):
        # Arrange
        layer = FakeChannelLayer()
        publisher = ExpertFinderEventPublisher(channel_layer=layer)

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            publisher.publish_experts_found(12, 5)

        # Assert
        self.assertEqual(layer.sent[0][1]["data"]["kind"], EXPERTS_FOUND)
        self.assertEqual(layer.sent[0][1]["data"]["expert_count"], 5)
        self.assertNotIn("progress", layer.sent[0][1]["data"])

    def test_publish_finished_and_failed(self):
        # Arrange
        layer = FakeChannelLayer()
        publisher = ExpertFinderEventPublisher(channel_layer=layer)

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            publisher.publish_finished(
                12,
                status="completed",
                progress=100,
                current_step="Done",
                expert_count=7,
            )
            publisher.publish_failed(
                12,
                status="failed",
                progress=0,
                current_step="Failed",
                error="boom",
            )

        # Assert
        kinds = [msg["data"]["kind"] for _, msg in layer.sent]
        self.assertEqual(kinds, [SEARCH_FINISHED, SEARCH_FAILED])
        self.assertEqual(layer.sent[0][1]["data"]["expert_count"], 7)
        self.assertEqual(layer.sent[1][1]["data"]["error"], "boom")

    def test_publish_survives_failing_channel_layer(self):
        # Arrange
        layer = FakeChannelLayer(error=RuntimeError("redis down"))
        publisher = ExpertFinderEventPublisher(channel_layer=layer)

        # Act & Assert
        with (
            self.assertLogs(
                "notification.services.notification_service", level="WARNING"
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            publisher.publish_experts_found(12, 1)
