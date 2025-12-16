import logging
from typing import List

from django.conf import settings

from personalize.types import SyncResult
from utils.aws import create_client

logger = logging.getLogger(__name__)


class SyncClient:
    BATCH_SIZE = 10

    def __init__(self):
        self.client = create_client("personalize-events")
        self.dataset_arn = settings.AWS_PERSONALIZE_DATASET_ARN
        self.tracking_id = settings.AWS_PERSONALIZE_TRACKING_ID

    def put_items(self, items: List[dict]) -> SyncResult:
        if settings.TESTING:
            return {"success": True, "synced": 0, "failed": 0, "errors": []}

        if not items:
            return {"success": True, "synced": 0, "failed": 0, "errors": []}

        synced = 0
        failed = 0
        errors = []

        for i in range(0, len(items), self.BATCH_SIZE):
            batch = items[i : i + self.BATCH_SIZE]

            try:
                self.client.put_items(datasetArn=self.dataset_arn, items=batch)
                synced += len(batch)
            except Exception as e:
                failed += len(batch)
                error_msg = f"Failed to sync batch {i // self.BATCH_SIZE + 1}: {str(e)}"
                errors.append(error_msg)

        return {
            "success": failed == 0,
            "synced": synced,
            "failed": failed,
            "errors": errors,
        }

    def put_events(
        self, user_id: str, session_id: str, events: List[dict]
    ) -> SyncResult:
        if settings.TESTING:
            return {"success": True, "synced": 0, "failed": 0, "errors": []}

        if not events:
            return {"success": True, "synced": 0, "failed": 0, "errors": []}

        synced = 0
        failed = 0
        errors = []

        for i in range(0, len(events), self.BATCH_SIZE):
            batch = events[i : i + self.BATCH_SIZE]

            try:
                self.client.put_events(
                    trackingId=self.tracking_id,
                    userId=user_id,
                    sessionId=session_id,
                    eventList=batch,
                )
                synced += len(batch)
            except Exception as e:
                failed += len(batch)
                batch_num = i // self.BATCH_SIZE + 1
                error_msg = f"Failed to send event batch {batch_num}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"[AWS Personalize] {error_msg}")

        return {
            "success": failed == 0,
            "synced": synced,
            "failed": failed,
            "errors": errors,
        }
