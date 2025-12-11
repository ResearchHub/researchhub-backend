import json
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
        if not items:
            logger.debug("[AWS Personalize] put_items called with empty list")
            return {"success": True, "synced": 0, "failed": 0, "errors": []}

        logger.info(f"[AWS Personalize] Syncing {len(items)} items to dataset")

        synced = 0
        failed = 0
        errors = []

        for i in range(0, len(items), self.BATCH_SIZE):
            batch = items[i : i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1

            try:
                # Log item IDs and full mapped properties
                for item in batch:
                    item_id = item.get("itemId")
                    properties_str = item.get("properties", "{}")
                    try:
                        properties = json.loads(properties_str)
                    except json.JSONDecodeError:
                        properties = properties_str

                    logger.info(
                        f"[AWS Personalize] Item {item_id} mapped data: {properties}"
                    )

                self.client.put_items(datasetArn=self.dataset_arn, items=batch)
                synced += len(batch)
                logger.info(f"[AWS Personalize] Batch {batch_num} synced successfully")
            except Exception as e:
                failed += len(batch)
                error_msg = f"Failed to sync batch {batch_num}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"[AWS Personalize] {error_msg}")

        logger.info(
            f"[AWS Personalize] Sync complete: {synced} synced, {failed} failed"
        )

        return {
            "success": failed == 0,
            "synced": synced,
            "failed": failed,
            "errors": errors,
        }

    def put_events(
        self, user_id: str, session_id: str, events: List[dict]
    ) -> SyncResult:
        if not events:
            logger.debug("[AWS Personalize] put_events called with empty list")
            return {"success": True, "synced": 0, "failed": 0, "errors": []}

        logger.info(
            f"[AWS Personalize] Sending {len(events)} events for user {user_id}"
        )

        synced = 0
        failed = 0
        errors = []

        for i in range(0, len(events), self.BATCH_SIZE):
            batch = events[i : i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1

            try:
                # Log event types being sent
                event_types = [event.get("eventType") for event in batch]
                logger.info(
                    f"[AWS Personalize] Sending event batch {batch_num}: {event_types}"
                )
                logger.debug(
                    f"[AWS Personalize] Event batch {batch_num} payload: {batch}"
                )

                self.client.put_events(
                    trackingId=self.tracking_id,
                    userId=user_id,
                    sessionId=session_id,
                    eventList=batch,
                )
                synced += len(batch)
                logger.info(
                    f"[AWS Personalize] Event batch {batch_num} sent successfully"
                )
            except Exception as e:
                failed += len(batch)
                error_msg = f"Failed to send event batch {batch_num}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"[AWS Personalize] {error_msg}")

        logger.info(
            f"[AWS Personalize] Events complete: {synced} sent, {failed} failed"
        )

        return {
            "success": failed == 0,
            "synced": synced,
            "failed": failed,
            "errors": errors,
        }
