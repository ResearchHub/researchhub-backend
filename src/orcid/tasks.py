from typing import Optional

from celery.utils.log import get_task_logger

from orcid.services.orcid_fetch_service import OrcidFetchService
from researchhub.celery import QUEUE_PULL_PAPERS, app

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_PULL_PAPERS, ignore_result=False)
def sync_orcid_papers_task(author_id: int, service: Optional[OrcidFetchService] = None) -> dict:
    """Sync papers from ORCID to ResearchHub for the given author."""
    service = service or OrcidFetchService()
    try:
        result = service.sync_papers(author_id)
        logger.info("Synced %s papers for author %s", result["papers_processed"], author_id)
        return result
    except Exception as e:
        logger.error("Failed to sync ORCID papers for author %s: %s", author_id, e)
        raise
