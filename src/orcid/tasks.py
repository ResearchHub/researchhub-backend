import logging

from orcid.services.orcid_fetch_service import OrcidFetchService
from researchhub.celery import app

logger = logging.getLogger(__name__)


@app.task
def sync_orcid_task(author_id: int) -> None:
    """Sync ORCID email and author stats for the given author."""
    service = OrcidFetchService()
    service.sync_orcid(author_id)
    logger.info("Completed ORCID email and author stats sync for author %d", author_id)
