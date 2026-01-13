import logging

from orcid.services.orcid_fetch_service import OrcidFetchService
from researchhub.celery import QUEUE_PULL_PAPERS, app

logger = logging.getLogger(__name__)


@app.task(queue=QUEUE_PULL_PAPERS, ignore_result=False)
def sync_orcid_task(author_id: int) -> dict:
    """Sync papers from ORCID to ResearchHub for the given author."""
    service = OrcidFetchService()
    result = service.sync_orcid(author_id)
    logger.info("Synced %d papers for author %d", result["papers_processed"], author_id)
    return result
