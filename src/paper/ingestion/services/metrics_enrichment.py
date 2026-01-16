import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from paper.ingestion.clients import BlueskyMetricsClient, GithubMetricsClient, XClient
from paper.ingestion.mappers import XMapper
from paper.models import Paper
from paper.related_models.x_post_model import XPost

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Result of enriching a single paper with metrics."""

    status: str  # "success", "not_found", "skipped", "error", or "retryable_error"
    metrics: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


@dataclass
class BatchEnrichmentResult:
    """Result of enriching multiple papers with metrics."""

    total: int
    success_count: int
    not_found_count: int
    error_count: int


class PaperMetricsEnrichmentService:
    """
    Service for enriching papers with external metrics data.

    This service handles fetching metrics and updating
    the corresponding papers in the database.
    """

    def __init__(
        self,
        bluesky_metrics_client: BlueskyMetricsClient,
        github_metrics_client: GithubMetricsClient,
        x_client: XClient,
        x_mapper: Optional[XMapper] = None,
    ):
        """
        Constructor.

        Args:
            github_metrics_client: Client for fetching GitHub metrics
            bluesky_metrics_client: Client for fetching Bluesky metrics
            x_client: Client for fetching X (Twitter) posts
            x_mapper: Mapper for X post data (optional, creates default if None)
        """
        self.github_metrics_client = github_metrics_client
        self.bluesky_metrics_client = bluesky_metrics_client
        self.x_client = x_client
        self.x_mapper = x_mapper or XMapper()

    def get_recent_papers_with_dois(self, days: int) -> List[int]:
        """
        Query papers published in the last N days that have DOIs.

        Args:
            days: Number of days to look back

        Returns:
            List of paper IDs
        """
        date_threshold = timezone.now() - timedelta(days=days)
        paper_ids = (
            Paper.objects.filter(
                paper_publish_date__gte=date_threshold, doi__isnull=False
            )
            .exclude(doi="")
            .values_list("id", flat=True)
        )
        return list(paper_ids)

    def enrich_paper_with_github_mentions(self, paper: Paper) -> EnrichmentResult:
        """
        Fetch GitHub mention metrics for the given paper and update its
        external_metadata.

        Args:
            paper: Paper instance to enrich
        Returns:
            EnrichmentResult with status and details
        """
        # Build search terms from DOI and title
        terms = [t for t in [paper.doi, paper.title] if t]
        if not terms:
            logger.warning(
                f"Paper {paper.id} has no DOI or title, skipping GitHub enrichment"
            )
            return EnrichmentResult(status="skipped", reason="no_doi_or_title")

        try:
            result = self.github_metrics_client.get_mentions(
                terms, search_areas=["code"]
            )

            if result is None:
                logger.info(f"No GitHub mentions found for paper {paper.id}")
                return EnrichmentResult(status="not_found", reason="no_github_mentions")

            self._update_paper_metrics(paper, {"github_mentions": result})

            logger.info(
                f"Successfully saved {result['total_mentions']} mentions for paper {paper.id}."
            )

            return EnrichmentResult(
                status="success",
                metrics={"github_mentions": result},
            )

        except Exception as e:
            error_message = f"Error fetching GitHub metrics for paper {paper.id}: {e}"

            # Check for retryable HTTP errors (rate limit, service unavailable)
            # GitHub uses 403 for rate limiting, unlike X which uses 429
            response = getattr(e, "response", None)
            if response is not None:
                status_code = getattr(response, "status_code", None)
                if status_code in (401, 403, 429, 503):
                    logger.warning(error_message)
                    return EnrichmentResult(status="retryable_error", reason=str(e))

            logger.error(error_message)
            return EnrichmentResult(status="error", reason=str(e))

    def enrich_paper_with_bluesky(self, paper: Paper) -> EnrichmentResult:
        """
        Fetch Bluesky metrics for the given paper and update its external_metadata.

        Args:
            paper: Paper instance to enrich

        Returns:
            EnrichmentResult with status and details
        """
        # Build search terms from DOI and title (similar to GitHub)
        terms = [t for t in [paper.doi, paper.title] if t]
        if not terms:
            logger.warning(
                f"Paper {paper.id} has no DOI or title, skipping Bluesky enrichment"
            )
            return EnrichmentResult(status="skipped", reason="no_doi_or_title")

        try:
            result = self.bluesky_metrics_client.get_metrics(terms)

            if result is None:
                logger.info(f"No Bluesky posts found for paper {paper.id}")
                return EnrichmentResult(status="not_found", reason="no_bluesky_posts")

            self._update_paper_metrics(paper, {"bluesky": result})

            logger.info(
                f"Successfully saved {result['post_count']} Bluesky posts for paper {paper.id}."
            )

            return EnrichmentResult(
                status="success",
                metrics={"bluesky": result},
            )

        except Exception as e:
            logger.error(f"Error fetching Bluesky metrics for paper {paper.id}: {e}")
            return EnrichmentResult(status="error", reason=str(e))

    def enrich_paper_with_x(self, paper: Paper) -> EnrichmentResult:
        """
        Fetch X (Twitter) metrics for the given paper and update its external_metadata.

        Args:
            paper: Paper instance to enrich

        Returns:
            EnrichmentResult with status and details
        """
        # Build search terms from DOI and title (similar to GitHub)
        terms = [t for t in [paper.doi, paper.title] if t]
        if not terms:
            logger.warning(
                f"Paper {paper.id} has no DOI or title, skipping X enrichment"
            )
            return EnrichmentResult(status="skipped", reason="no_doi_or_title")

        # Get hub slugs for bot filtering
        hub_slugs = list(paper.hubs.values_list("slug", flat=True))

        try:
            posts = self.x_client.search_posts(
                terms,
                external_source=paper.external_source,
                hub_slugs=hub_slugs,
            )

            if posts is None:
                logger.info(f"No X posts found for paper {paper.id}")
                return EnrichmentResult(status="not_found", reason="no_x_posts")

            # Save individual X posts to the database
            if posts:
                self._save_x_posts(paper, posts)

            # Extract and store aggregated metrics in external_metadata
            metrics = self.x_mapper.extract_metrics(posts)
            self._update_paper_metrics(paper, {"x": metrics})

            logger.info(
                f"Successfully saved {metrics['post_count']} X posts for paper {paper.id}."
            )

            return EnrichmentResult(
                status="success",
                metrics={"x": metrics},
            )

        except Exception as e:
            error_message = f"Error fetching X metrics for paper {paper.id}: {e}"

            # Check for retryable HTTP errors (rate limit, service unavailable)
            response = getattr(e, "response", None)
            if response is not None:
                status_code = getattr(response, "status_code", None)
                if status_code in (429, 503):
                    logger.warning(error_message)
                    return EnrichmentResult(status="retryable_error", reason=str(e))

            logger.error(error_message)
            return EnrichmentResult(status="error", reason=str(e))

    def _update_paper_metrics(self, paper: Paper, metrics: Dict[str, Any]) -> None:
        """
        Update paper's external_metadata with metrics while preserving existing metrics.

        New metrics are merged with existing metrics, allowing multiple enrichment
        sources (e.g., Bluesky and GitHub) to coexist without overwriting each other.
        """
        if paper.external_metadata is None:
            paper.external_metadata = {}

        # Get existing metrics or start with empty dict
        existing_metrics = paper.external_metadata.get("metrics", {})
        if not isinstance(existing_metrics, dict):
            existing_metrics = {}

        # Serialize and deserialize to ensure all values are JSON-safe
        new_metrics = json.loads(json.dumps(metrics, default=str))

        # Merge new metrics into existing metrics
        existing_metrics.update(new_metrics)
        paper.external_metadata["metrics"] = existing_metrics

        paper.save(update_fields=["external_metadata"])

    def _save_x_posts(self, paper: Paper, posts: List[Dict[str, Any]]) -> int:
        """
        Save X posts to the database, updating existing posts or creating new ones.

        Args:
            paper: Paper instance the posts reference
            posts: List of post dicts from XMetricsClient

        Returns:
            Number of posts created or updated
        """
        x_posts = self.x_mapper.map_to_x_posts(posts)

        for x_post in x_posts:
            XPost.objects.update_or_create(
                paper=paper,
                post_id=x_post.post_id,
                defaults={
                    "author_id": x_post.author_id,
                    "text": x_post.text,
                    "posted_date": x_post.posted_date,
                    "like_count": x_post.like_count,
                    "repost_count": x_post.repost_count,
                    "reply_count": x_post.reply_count,
                    "quote_count": x_post.quote_count,
                    "impression_count": x_post.impression_count,
                },
            )
