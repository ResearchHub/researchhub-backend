from django.db import transaction

from notification.services import NotificationService

EVENT_TYPE = "expert_finder_event"

SEARCH_PROGRESS = "search_progress"
EXPERTS_FOUND = "experts_found"
SEARCH_FINISHED = "search_finished"
SEARCH_FAILED = "search_failed"


def search_group(search_id: int | str) -> str:
    """The channel-layer group carrying one expert search's events."""
    return f"expert_finder_search_{int(search_id)}"


class ExpertFinderEventPublisher:
    """Publishes Expert Finder events to a search's channel-layer group.

    The channel layer is injectable for tests; by default each send resolves
    the configured layer at publish time, so a Celery worker that never
    serves WebSockets still publishes through the shared Redis backend.
    """

    def __init__(self, channel_layer=None):
        self._channel_layer = channel_layer

    def publish_progress(
        self,
        search_id: int | str,
        *,
        status: str,
        progress: int,
        current_step: str,
    ) -> None:
        """Emit ``search_progress`` for an in-flight search."""
        self._publish(
            search_id,
            {
                "search_id": int(search_id),
                "kind": SEARCH_PROGRESS,
                "status": status,
                "progress": progress,
                "current_step": current_step,
            },
        )

    def publish_experts_found(
        self,
        search_id: int | str,
        expert_count: int,
    ) -> None:
        """Emit ``experts_found`` with a kept/total count (not a progress %)."""
        self._publish(
            search_id,
            {
                "search_id": int(search_id),
                "kind": EXPERTS_FOUND,
                "expert_count": int(expert_count),
            },
        )

    def publish_finished(
        self,
        search_id: int | str,
        *,
        status: str,
        progress: int,
        current_step: str,
        expert_count: int,
        error: str | None = None,
    ) -> None:
        """Emit ``search_finished`` for a completed search."""
        data: dict = {
            "search_id": int(search_id),
            "kind": SEARCH_FINISHED,
            "status": status,
            "progress": progress,
            "current_step": current_step,
            "expert_count": int(expert_count),
        }
        if error:
            data["error"] = error
        self._publish(search_id, data)

    def publish_failed(
        self,
        search_id: int | str,
        *,
        status: str,
        progress: int,
        current_step: str,
        error: str,
    ) -> None:
        """Emit ``search_failed`` for a terminal failure."""
        self._publish(
            search_id,
            {
                "search_id": int(search_id),
                "kind": SEARCH_FAILED,
                "status": status,
                "progress": progress,
                "current_step": current_step,
                "error": error,
            },
        )

    def _publish(self, search_id: int | str, data: dict) -> None:
        transaction.on_commit(
            lambda: self._send(search_id, data),
            robust=True,
        )

    def _send(self, search_id: int | str, data: dict) -> None:
        NotificationService(channel_layer=self._channel_layer).send_channel_message(
            search_group(search_id),
            {"type": EVENT_TYPE, "data": data},
        )
