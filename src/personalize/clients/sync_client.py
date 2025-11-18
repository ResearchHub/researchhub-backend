from typing import List

from django.conf import settings

from personalize.types import SyncResult
from utils.aws import create_client


class SyncClient:
    BATCH_SIZE = 10

    def __init__(self):
        self.client = create_client("personalize-events")
        self.dataset_arn = settings.AWS_PERSONALIZE_DATASET_ARN

    def put_items(self, items: List[dict]) -> SyncResult:
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
