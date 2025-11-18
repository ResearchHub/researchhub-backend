import logging

from celery.utils.log import get_task_logger
from django.apps import apps

from personalize.services.sync_service import SyncService
from researchhub.celery import QUEUE_PAPER_MISC, app

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_PAPER_MISC, max_retries=3, retry_backoff=True)
def sync_paper_to_personalize_task(paper_id):
    Paper = apps.get_model("paper.Paper")

    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.error(f"Paper {paper_id} not found for Personalize sync")
        return

    unified_doc = paper.unified_document

    if not unified_doc:
        logger.warning(
            f"Paper {paper_id} has no unified_document, skipping Personalize sync"
        )
        return

    logger.info(
        f"Syncing paper {paper_id} to Personalize (unified_doc: {unified_doc.id})"
    )

    try:
        personalize_sync_service = SyncService()
        result = personalize_sync_service.sync_item(unified_doc)

        if result["success"]:
            logger.info(
                f"Successfully synced paper {paper_id} to Personalize: {result}"
            )
        else:
            logger.error(f"Failed to sync paper {paper_id} to Personalize: {result}")
            raise Exception(f"Sync failed: {result}")

    except Exception as e:
        logger.error(
            f"Exception syncing paper {paper_id} to Personalize: {str(e)}",
            exc_info=True,
        )
        raise
