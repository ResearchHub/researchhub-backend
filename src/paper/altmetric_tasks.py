import logging
from datetime import timedelta

from celery.exceptions import MaxRetriesExceededError
from django.utils import timezone

from paper.models import Paper
from researchhub.celery import QUEUE_PAPER_MISC, app
from utils import sentry
from utils.altmetric import Altmetric

logger = logging.getLogger(__name__)


def extract_relevant_altmetric_fields(altmetric_data):
    """
    Extract only count, score, and percentile fields from Altmetric data.
    """
    if not altmetric_data:
        return None

    relevant_fields = {
        # Core score
        "score": altmetric_data.get("score"),
        # Citation counts
        "cited_by_posts_count": altmetric_data.get("cited_by_posts_count"),
        "cited_by_accounts_count": altmetric_data.get("cited_by_accounts_count"),
        "cited_by_msm_count": altmetric_data.get("cited_by_msm_count"),
        "cited_by_feeds_count": altmetric_data.get("cited_by_feeds_count"),
        "cited_by_patents_count": altmetric_data.get("cited_by_patents_count"),
        "cited_by_wikipedia_count": altmetric_data.get("cited_by_wikipedia_count"),
        "cited_by_tweeters_count": altmetric_data.get("cited_by_tweeters_count"),
        "cited_by_fbwalls_count": altmetric_data.get("cited_by_fbwalls_count"),
        "cited_by_gplus_count": altmetric_data.get("cited_by_gplus_count"),
        "cited_by_bluesky_count": altmetric_data.get("cited_by_bluesky_count"),
        # Reader counts
        "readers_count": altmetric_data.get("readers_count"),
    }

    # Add reader platform counts if available
    readers = altmetric_data.get("readers", {})
    if readers:
        relevant_fields["readers_mendeley"] = readers.get("mendeley")
        relevant_fields["readers_citeulike"] = readers.get("citeulike")
        relevant_fields["readers_connotea"] = readers.get("connotea")

    # Add context percentiles and ranks
    context = altmetric_data.get("context", {})
    context_types = ["all", "journal", "similar_age_3m", "similar_age_journal_3m"]
    for context_type in context_types:
        if context_type in context:
            ctx_data = context[context_type]
            relevant_fields[f"context_{context_type}_pct"] = ctx_data.get("pct")
            relevant_fields[f"context_{context_type}_rank"] = ctx_data.get("rank")
            relevant_fields[f"context_{context_type}_count"] = ctx_data.get("count")
            relevant_fields[f"context_{context_type}_higher_than"] = ctx_data.get(
                "higher_than"
            )

    # Add cohort counts
    cohorts = altmetric_data.get("cohorts", {})
    if cohorts:
        relevant_fields["cohorts_pub"] = cohorts.get("pub")
        relevant_fields["cohorts_sci"] = cohorts.get("sci")
        relevant_fields["cohorts_com"] = cohorts.get("com")

    # Add history scores
    history = altmetric_data.get("history", {})
    if history:
        for period in ["1d", "1w", "1m", "3m", "6m", "1y", "at"]:
            if period in history:
                relevant_fields[f"history_{period}"] = history[period]

    # Remove None values to save space
    return {k: v for k, v in relevant_fields.items() if v is not None}


@app.task(queue=QUEUE_PAPER_MISC, bind=True, max_retries=3)
def enrich_papers_with_altmetric_data(self, retry=0):
    """
    Enrich papers created in the last day with Altmetric data.
    This task runs daily and fetches Altmetric scores and social media mentions
    for recently ingested papers that have DOIs.
    """
    logger.info("Starting Altmetric enrichment for papers from the last day")

    # Get papers created in the last day that have DOIs
    date_threshold = timezone.now() - timedelta(days=100)
    papers = (
        Paper.objects.filter(created_date__gte=date_threshold, doi__isnull=False)
        .exclude(doi="")
        .values_list("id", "doi")
    )

    total_papers = len(papers)
    logger.info(f"Found {total_papers} papers to enrich with Altmetric data")

    if total_papers == 0:
        return {"status": "success", "papers_processed": 0}

    # Initialize Altmetric client
    altmetric_client = Altmetric()

    # Process papers
    success_count = 0
    error_count = 0
    not_found_count = 0

    try:
        for paper_id, doi in papers:
            try:
                altmetric_data = altmetric_client.get_altmetric_data(doi)

                if altmetric_data:
                    # Update the paper's external_metadata
                    paper = Paper.objects.get(id=paper_id)

                    # Initialize external_metadata if it doesn't exist
                    if paper.external_metadata is None:
                        paper.external_metadata = {}

                    # Extract only relevant fields
                    relevant_data = extract_relevant_altmetric_fields(altmetric_data)

                    # Store Altmetric data with timestamp
                    paper.external_metadata["altmetric"] = relevant_data
                    paper.external_metadata["altmetric_updated_at"] = (
                        timezone.now().isoformat()
                    )

                    paper.save(update_fields=["external_metadata"])
                    success_count += 1

                    logger.debug(
                        f"Successfully enriched paper {paper_id} with Altmetric data"
                    )
                else:
                    not_found_count += 1
                    logger.debug(
                        f"No Altmetric data found for paper {paper_id} (DOI: {doi})"
                    )

            except Exception as e:
                error_count += 1
                logger.error(
                    f"Error processing paper {paper_id} (DOI: {doi}): {str(e)}",
                    exc_info=True,
                )
                sentry.log_error(
                    e, message=f"Failed to enrich paper {paper_id} with Altmetric data"
                )

        logger.info(
            f"Altmetric enrichment completed. "
            f"Success: {success_count}, Not found: {not_found_count}, "
            f"Errors: {error_count}"
        )

        return {
            "status": "success",
            "papers_processed": total_papers,
            "success_count": success_count,
            "not_found_count": not_found_count,
            "error_count": error_count,
        }

    except Exception as e:
        logger.error(f"Fatal error in Altmetric enrichment task: {str(e)}")
        sentry.log_error(e, message="Fatal error in Altmetric enrichment task")

        try:
            # Retry the task
            self.retry(args=[retry + 1], exc=e, countdown=60 * (retry + 1))
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for Altmetric enrichment task")
            raise


@app.task(queue=QUEUE_PAPER_MISC)
def enrich_single_paper_with_altmetric(paper_id: int):
    """
    Enrich a single paper with Altmetric data.
    This can be used for on-demand enrichment or retrying failed papers.
    """
    try:
        paper = Paper.objects.get(id=paper_id)

        if not paper.doi:
            logger.warning(
                f"Paper {paper_id} has no DOI, skipping Altmetric enrichment"
            )
            return {"status": "skipped", "reason": "no_doi"}

        altmetric_client = Altmetric()
        altmetric_data = altmetric_client.get_altmetric_data(paper.doi)

        if altmetric_data:
            # Initialize external_metadata if it doesn't exist
            if paper.external_metadata is None:
                paper.external_metadata = {}

            # Extract only relevant fields
            relevant_data = extract_relevant_altmetric_fields(altmetric_data)

            # Store Altmetric data with timestamp
            paper.external_metadata["altmetric"] = relevant_data
            paper.external_metadata["altmetric_updated_at"] = timezone.now().isoformat()

            paper.save(update_fields=["external_metadata"])

            logger.info(f"Successfully enriched paper {paper_id} with Altmetric data")
            return {"status": "success", "altmetric_score": altmetric_data.get("score")}
        else:
            logger.info(f"No Altmetric data found for paper {paper_id}")
            return {"status": "not_found"}

    except Paper.DoesNotExist:
        logger.error(f"Paper {paper_id} not found")
        return {"status": "error", "reason": "paper_not_found"}
    except Exception as e:
        logger.error(f"Error enriching paper {paper_id} with Altmetric data: {str(e)}")
        sentry.log_error(
            e, message=f"Failed to enrich paper {paper_id} with Altmetric data"
        )
        return {"status": "error", "reason": str(e)}
