import logging

from celery.exceptions import MaxRetriesExceededError
from django.conf import settings

from paper.ingestion.clients import (
    BlueskyMetricsClient,
    GithubClient,
    GithubMetricsClient,
    XMetricsClient,
)
from paper.ingestion.clients.enrichment.altmetric import AltmetricClient
from paper.ingestion.clients.enrichment.openalex import OpenAlexClient
from paper.ingestion.mappers import AltmetricMapper, OpenAlexMapper
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

    service = PaperMetricsEnrichmentService(
        altmetric_client=AltmetricClient(),
        altmetric_mapper=AltmetricMapper(),
        bluesky_metrics_client=None,
        github_metrics_client=None,
        x_metrics_client=None,
    )

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


@app.task(queue=QUEUE_PAPER_MISC)
def update_recent_papers_with_github_metrics(days: int = 7):
    """
    Dispatch individual tasks to fetch and update GitHub metrics
    for papers created in the last N days.

    Each paper is processed by a separate rate-limited task.
    This dispatcher does not retry - individual enrichment tasks handle their own retries.
    """
    logger.info(f"Starting GitHub metrics update for papers (last {days} days)")

    github_metrics_client = _create_github_metrics_client()
    service = PaperMetricsEnrichmentService(
        altmetric_client=None,
        altmetric_mapper=None,
        bluesky_metrics_client=None,
        github_metrics_client=github_metrics_client,
        x_metrics_client=None,
    )

    papers = service.get_recent_papers_with_dois(days)

    total_papers = len(papers)
    logger.info(f"Found {total_papers} papers to update with GitHub metrics")

    if total_papers == 0:
        return {
            "status": "success",
            "papers_processed": 0,
            "message": f"No papers with DOIs found in last {days} days",
        }

    # Dispatch individual tasks per paper
    for paper_id in papers:
        enrich_paper_with_github_metrics.delay(paper_id)

    logger.info(f"Dispatched {total_papers} individual GitHub enrichment tasks")

    return {
        "status": "success",
        "papers_dispatched": total_papers,
        "message": f"Dispatched {total_papers} enrichment tasks",
    }


@app.task(queue=QUEUE_PAPER_MISC, bind=True, max_retries=3, rate_limit="30/m")
def enrich_paper_with_github_metrics(self, paper_id: int, retry: int = 0):
    """
    Fetch and update GitHub metrics for a single paper.

    Args:
        paper_id: ID of the paper to enrich
        retry: Current retry attempt number

    Returns:
        Dict with status and details
    """
    from paper.models import Paper

    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.error(f"Paper {paper_id} not found")
        return {
            "status": "error",
            "paper_id": paper_id,
            "reason": "paper_not_found",
        }

    if not paper.doi:
        logger.warning(f"Paper {paper_id} has no DOI, skipping GitHub enrichment")
        return {
            "status": "skipped",
            "paper_id": paper_id,
            "reason": "no_doi",
        }

    github_metrics_client = _create_github_metrics_client()
    service = PaperMetricsEnrichmentService(
        altmetric_client=None,
        altmetric_mapper=None,
        bluesky_metrics_client=None,
        github_metrics_client=github_metrics_client,
        x_metrics_client=None,
    )

    try:
        enrichment_result = service.enrich_paper_with_github_mentions(paper)

        if enrichment_result.status == "not_found":
            return {
                "status": "not_found",
                "paper_id": paper_id,
                "doi": paper.doi,
            }

        if enrichment_result.status == "success":
            github_metrics = enrichment_result.metrics.get("github_mentions", {})
            logger.info(
                f"Successfully enriched paper {paper_id} with GitHub metrics: "
                f"{github_metrics.get('total_mentions', 0)} total mentions"
            )

            return {
                "status": "success",
                "paper_id": paper_id,
                "doi": paper.doi,
                "metrics": github_metrics,
            }

        # Handle other statuses (skipped, error)
        return {
            "status": enrichment_result.status,
            "paper_id": paper_id,
            "doi": paper.doi,
            "reason": enrichment_result.reason,
        }

    except Exception as e:
        logger.error(f"Error enriching paper {paper_id} with GitHub metrics: {str(e)}")
        sentry.log_error(
            e, message=f"Error enriching paper {paper_id} with GitHub metrics"
        )

        try:
            # Retry with exponential backoff
            self.retry(args=[paper_id, retry + 1], exc=e, countdown=60 * (retry + 1))
        except MaxRetriesExceededError:
            logger.error(
                f"Max retries exceeded for GitHub enrichment of paper {paper_id}"
            )
            return {
                "status": "error",
                "paper_id": paper_id,
                "reason": str(e),
            }


def _create_github_metrics_client() -> GithubMetricsClient:
    github_token = settings.GITHUB_TOKEN or None
    client = GithubClient(api_token=github_token)
    return GithubMetricsClient(github_client=client)


@app.task(queue=QUEUE_PAPER_MISC)
def update_recent_papers_with_bluesky_metrics(days: int = 7):
    """
    Dispatch individual tasks to fetch and update Bluesky metrics
    for papers created in the last N days.

    Each paper is processed by a separate rate-limited task.
    This dispatcher does not retry - individual enrichment tasks handle their own retries.
    """
    logger.info(f"Starting Bluesky metrics update for papers (last {days} days)")

    service = PaperMetricsEnrichmentService(
        altmetric_client=None,
        altmetric_mapper=None,
        bluesky_metrics_client=BlueskyMetricsClient(),
        github_metrics_client=None,
        x_metrics_client=None,
    )

    papers = service.get_recent_papers_with_dois(days)

    total_papers = len(papers)
    logger.info(f"Found {total_papers} papers to update with Bluesky metrics")

    if total_papers == 0:
        return {
            "status": "success",
            "papers_processed": 0,
            "message": f"No papers with DOIs found in last {days} days",
        }

    # Dispatch individual tasks per paper
    for paper_id in papers:
        enrich_paper_with_bluesky_metrics.delay(paper_id)

    logger.info(f"Dispatched {total_papers} individual Bluesky enrichment tasks")

    return {
        "status": "success",
        "papers_dispatched": total_papers,
        "message": f"Dispatched {total_papers} enrichment tasks",
    }


@app.task(queue=QUEUE_PAPER_MISC, bind=True, max_retries=3, rate_limit="30/m")
def enrich_paper_with_bluesky_metrics(self, paper_id: int, retry: int = 0):
    """
    Fetch and update Bluesky metrics for a single paper.

    Args:
        paper_id: ID of the paper to enrich
        retry: Current retry attempt number

    Returns:
        Dict with status and details
    """
    from paper.models import Paper

    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.error(f"Paper {paper_id} not found")
        return {
            "status": "error",
            "paper_id": paper_id,
            "reason": "paper_not_found",
        }

    if not paper.doi:
        logger.warning(f"Paper {paper_id} has no DOI, skipping Bluesky enrichment")
        return {
            "status": "skipped",
            "paper_id": paper_id,
            "reason": "no_doi",
        }

    service = PaperMetricsEnrichmentService(
        altmetric_client=None,
        altmetric_mapper=None,
        bluesky_metrics_client=BlueskyMetricsClient(),
        github_metrics_client=None,
        x_metrics_client=None,
    )

    try:
        enrichment_result = service.enrich_paper_with_bluesky(paper)

        if enrichment_result.status == "not_found":
            return {
                "status": "not_found",
                "paper_id": paper_id,
                "doi": paper.doi,
            }

        if enrichment_result.status == "success":
            bluesky_metrics = enrichment_result.metrics.get("bluesky", {})
            logger.info(
                f"Successfully enriched paper {paper_id} with Bluesky metrics: "
                f"{bluesky_metrics.get('post_count', 0)} posts"
            )

            return {
                "status": "success",
                "paper_id": paper_id,
                "doi": paper.doi,
                "metrics": bluesky_metrics,
            }

        # Handle other statuses (skipped, error)
        return {
            "status": enrichment_result.status,
            "paper_id": paper_id,
            "doi": paper.doi,
            "reason": enrichment_result.reason,
        }

    except Exception as e:
        logger.error(f"Error enriching paper {paper_id} with Bluesky metrics: {str(e)}")
        sentry.log_error(
            e, message=f"Error enriching paper {paper_id} with Bluesky metrics"
        )

        try:
            # Retry with exponential backoff
            self.retry(args=[paper_id, retry + 1], exc=e, countdown=60 * (retry + 1))
        except MaxRetriesExceededError:
            logger.error(
                f"Max retries exceeded for Bluesky enrichment of paper {paper_id}"
            )
            return {
                "status": "error",
                "paper_id": paper_id,
                "reason": str(e),
            }
