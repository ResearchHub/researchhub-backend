import logging

from celery.exceptions import MaxRetriesExceededError

from paper.ingestion.clients.altmetric import AltmetricClient
from paper.ingestion.clients.openalex import OpenAlexClient
from paper.ingestion.mappers.altmetric import AltmetricMapper
from paper.ingestion.mappers.openalex import OpenAlexMapper
from paper.ingestion.services.metrics_enrichment import PaperMetricsEnrichmentService
from paper.ingestion.services.openalex_enrichment import PaperOpenAlexEnrichmentService
from researchhub.celery import QUEUE_PAPER_MISC, app
from utils import sentry

logger = logging.getLogger(__name__)


@app.task(queue=QUEUE_PAPER_MISC, bind=True, max_retries=3)
def update_recent_papers_with_metrics(self, days: int = 7, retry: int = 0):
    """
    Fetch and update metrics for papers created in the last N days.
    """
    logger.info(f"Starting metrics update for papers (last {days} days)")

    service = PaperMetricsEnrichmentService(AltmetricClient(), AltmetricMapper())

    papers = service.get_recent_papers_with_dois(days)

    total_papers = len(papers)
    logger.info(f"Found {total_papers} papers to update with Altmetric metrics")

    if total_papers == 0:
        return {
            "status": "success",
            "papers_processed": 0,
            "message": f"No papers with DOIs found in last {days} days",
        }

    try:
        results = service.enrich_papers_batch(papers)

        logger.info(
            f"Altmetric metrics update completed. "
            f"Success: {results.success_count}, Not found: {results.not_found_count}, "
            f"Errors: {results.error_count}"
        )

        return {
            "status": "success",
            "papers_processed": results.total,
            "success_count": results.success_count,
            "not_found_count": results.not_found_count,
            "error_count": results.error_count,
        }

    except Exception as e:
        logger.error(f"Fatal error in paper metrics update task: {str(e)}")
        sentry.log_error(e, message="Fatal error in paper metrics update task")

        try:
            # Retry in case of failure
            self.retry(args=[days, retry + 1], exc=e, countdown=60 * (retry + 1))
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for Altmetric metrics update task")
            raise


@app.task(queue=QUEUE_PAPER_MISC, bind=True, max_retries=3)
def enrich_papers_with_openalex(self, days: int = 30, retry: int = 0):
    """
    Enrich papers created in the last N days with OpenAlex metrics.
    """
    logger.info(f"Starting OpenAlex enrichment for papers (last {days} days)")

    service = PaperOpenAlexEnrichmentService(OpenAlexClient(), OpenAlexMapper())

    papers = service.get_recent_papers_with_dois(days)

    total_papers = len(papers)
    logger.info(f"Found {total_papers} papers to enrich with OpenAlex metrics")

    if total_papers == 0:
        return {
            "status": "success",
            "papers_processed": 0,
            "message": f"No papers with DOIs found in last {days} days",
        }
    try:
        results = service.enrich_papers_batch(papers)

        logger.info(
            f"OpenAlex enrichment completed. "
            f"Success: {results.success_count}, Not found: {results.not_found_count}, "
            f"Errors: {results.error_count}"
        )

        return {
            "status": "success",
            "papers_processed": results.total,
            "success_count": results.success_count,
            "not_found_count": results.not_found_count,
            "error_count": results.error_count,
        }
    except Exception as e:
        logger.error(f"Fatal error in OpenAlex enrichment task: {str(e)}")
        sentry.log_error(e, message="Fatal error in OpenAlex enrichment task")

        try:
            # Retry in case of failure
            self.retry(args=[days, retry + 1], exc=e, countdown=60 * (retry + 1))
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for OpenAlex enrichment task")
            raise
