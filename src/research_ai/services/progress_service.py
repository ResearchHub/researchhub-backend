import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Union

import redis
from django.conf import settings

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Supported task types for progress tracking."""

    EXPERTS = "experts"


def _get_redis_url() -> str:
    """Build Redis URL from Django settings (use DB 3 for progress to avoid clashes)."""
    host = getattr(settings, "REDIS_HOST", "localhost")
    port = getattr(settings, "REDIS_PORT", 6379)
    return f"redis://{host}:{port}/3"


class ProgressService:
    """Progress tracking service using Redis Pub/Sub."""

    def __init__(self):
        self.redis_url = _get_redis_url()
        self.redis_client = redis.from_url(self.redis_url)
        logger.debug("ProgressService initialized with Redis")

    def publish_progress_sync(
        self,
        task_type: Union[TaskType, str],
        task_id: str,
        progress_data: dict[str, Any],
    ) -> None:
        """
        Publish progress update to Redis channel (synchronous, for Celery workers).

        Args:
            task_type: Type of task (e.g. "experts").
            task_id: Unique task identifier (e.g. ExpertSearch UUID).
            progress_data: Dict with status, progress, currentStep, error/result.
        """
        try:
            if isinstance(task_type, TaskType):
                task_type = task_type.value
            channel = f"progress:{task_type}:{task_id}"
            message = {
                "task_type": task_type,
                "task_id": task_id,
                "timestamp": datetime.utcnow().isoformat(),
                **progress_data,
            }
            message_json = json.dumps(message)
            self.redis_client.publish(channel, message_json)
        except Exception as e:
            logger.warning(
                "Failed to publish progress for %s:%s: %s",
                task_type,
                task_id,
                e,
            )
            # Do not raise; progress publishing must not break the main workflow

    def subscribe_to_progress_sync(
        self,
        task_type: Union[TaskType, str],
        task_id: str,
    ):
        """
        Subscribe to progress updates (sync). Yields parsed message dicts.
        For use in Django SSE view: loop over this and format as SSE.
        """
        if isinstance(task_type, TaskType):
            task_type = task_type.value
        channel = f"progress:{task_type}:{task_id}"
        pubsub = self.redis_client.pubsub()
        try:
            pubsub.subscribe(channel)
            while True:
                message = pubsub.get_message(timeout=1.0)
                if message is None:
                    yield None  # no message this tick
                    continue
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message.get("data") or "{}")
                    yield data
                except (TypeError, ValueError):
                    continue
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except Exception:
                pass
