import logging

from celery.exceptions import MaxRetriesExceededError
from django.conf import settings
from django.core.cache import cache

from paper.ingestion.clients import (
    BlueskyMetricsClient,
    GithubClient,
    GithubMetricsClient,
    XMetricsClient,
)
from paper.ingestion.clients.enrichment.openalex import OpenAlexClient
from paper.ingestion.mappers import OpenAlexMapper
from paper.ingestion.services.metrics_enrichment import PaperMetricsEnrichmentService
from paper.ingestion.services.openalex_enrichment import PaperOpenAlexEnrichmentService
from researchhub.celery import QUEUE_PAPER_METRICS, QUEUE_PAPER_MISC, app
from utils import sentry

logger = logging.getLogger(__name__)


X_API_BACKOFF_KEY = "x_api_backoff"
X_API_BACKOFF_SECONDS = 60


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


@app.task(queue=QUEUE_PAPER_METRICS)
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


@app.task(queue=QUEUE_PAPER_METRICS, bind=True, max_retries=3, rate_limit="10/m")
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


@app.task(queue=QUEUE_PAPER_METRICS)
def update_recent_papers_with_bluesky_metrics(days: int = 7):
    """
    Dispatch individual tasks to fetch and update Bluesky metrics
    for papers created in the last N days.

    Each paper is processed by a separate rate-limited task.
    This dispatcher does not retry - individual enrichment tasks handle their own retries.
    """
    logger.info(f"Starting Bluesky metrics update for papers (last {days} days)")

    service = PaperMetricsEnrichmentService(
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


@app.task(queue=QUEUE_PAPER_METRICS, bind=True, max_retries=3, rate_limit="600/m")
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


@app.task(queue=QUEUE_PAPER_METRICS)
def update_recent_papers_with_x_metrics(days: int = 7):
    """
    Dispatch individual tasks to fetch and update X metrics
    for papers created in the last N days.

    Each paper is processed by a separate rate-limited task.
    This dispatcher does not retry - individual tasks handle their own retries.
    """
    logger.info(f"Starting X metrics update for papers (last {days} days)")

    service = PaperMetricsEnrichmentService(
        bluesky_metrics_client=None,
        github_metrics_client=None,
        x_metrics_client=XMetricsClient(),
    )

    papers = service.get_recent_papers_with_dois(days)

    total_papers = len(papers)
    logger.info(f"Found {total_papers} papers to update with X metrics")

    if total_papers == 0:
        return {
            "status": "success",
            "papers_processed": 0,
            "message": f"No papers with DOIs found in last {days} days",
        }

    # Dispatch individual tasks per paper
    for paper_id in papers:
        enrich_paper_with_x_metrics.delay(paper_id)

    logger.info(f"Dispatched {total_papers} individual X enrichment tasks")

    return {
        "status": "success",
        "papers_dispatched": total_papers,
        "message": f"Dispatched {total_papers} enrichment tasks",
    }


@app.task(
    queue=QUEUE_PAPER_METRICS,
    bind=True,
    max_retries=5,
    rate_limit="0.5/s",
)
def enrich_paper_with_x_metrics(self, paper_id: int):
    """
    Fetch and update X metrics for a single paper.

    Uses shared backoff via cache for rate limit errors (429, 503).
    When one task hits a rate limit, all tasks back off for 60 seconds.

    Args:
        paper_id: ID of the paper to enrich

    Returns:
        Dict with status and details
    """
    from paper.models import Paper

    # Check if we're in backoff mode due to a previous rate limit error
    if cache.get(X_API_BACKOFF_KEY):
        raise self.retry(countdown=X_API_BACKOFF_SECONDS)

    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.error(f"Paper {paper_id} not found")
        return {
            "status": "error",
            "paper_id": paper_id,
            "reason": "paper_not_found",
        }

    # Check that paper has at least a DOI or title for searching
    if not paper.doi and not paper.title:
        logger.warning(f"Paper {paper_id} has no DOI or title, skipping X enrichment")
        return {
            "status": "skipped",
            "paper_id": paper_id,
            "reason": "no_doi_or_title",
        }

    service = PaperMetricsEnrichmentService(
        bluesky_metrics_client=None,
        github_metrics_client=None,
        x_metrics_client=XMetricsClient(),
    )

    try:
        enrichment_result = service.enrich_paper_with_x(paper)

        if enrichment_result.status == "not_found":
            return {
                "status": "not_found",
                "paper_id": paper_id,
                "doi": paper.doi,
            }

        if enrichment_result.status == "success":
            x_metrics = enrichment_result.metrics.get("x", {})
            logger.info(
                f"Successfully enriched paper {paper_id} with X metrics: "
                f"{x_metrics.get('post_count', 0)} posts"
            )

            return {
                "status": "success",
                "paper_id": paper_id,
                "doi": paper.doi,
                "metrics": x_metrics,
            }

        # Handle other statuses (skipped, error)
        return {
            "status": enrichment_result.status,
            "paper_id": paper_id,
            "doi": paper.doi,
            "reason": enrichment_result.reason,
        }

    except Exception as e:
        # Check for rate limit errors (429, 503) regardless of exception type
        # The X SDK may wrap HTTP errors in its own exception type
        response = getattr(e, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code in (429, 503):
                # Set backoff flag so other tasks wait
                logger.warning(
                    f"X API rate limit hit ({status_code}), "
                    f"setting {X_API_BACKOFF_SECONDS}s backoff for all tasks"
                )
                cache.set(X_API_BACKOFF_KEY, True, timeout=X_API_BACKOFF_SECONDS)
                raise self.retry(countdown=X_API_BACKOFF_SECONDS)

        logger.error(f"Error enriching paper {paper_id} with X metrics: {str(e)}")
        sentry.log_error(e, message=f"Error enriching paper {paper_id} with X metrics")
        return {
            "status": "error",
            "paper_id": paper_id,
            "reason": str(e),
        }
