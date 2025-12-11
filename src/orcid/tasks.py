from celery.utils.log import get_task_logger

from orcid.services.orcid_service import sync_orcid_papers
from researchhub.celery import QUEUE_PULL_PAPERS, app

logger = get_task_logger(__name__)


@app.task(queue=QUEUE_PULL_PAPERS)
def fetch_orcid_works_task(author_id):
    try:
        result = sync_orcid_papers(author_id)
        logger.info(f"Synced {result['papers_processed']} papers for author {author_id}")
        return result
    except Exception as e:
        logger.error(f"Failed to sync ORCID papers for author {author_id}: {e}")
        raise

