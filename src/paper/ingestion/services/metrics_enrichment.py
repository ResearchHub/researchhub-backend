import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

from dateutil import parser as date_parser
from django.utils import timezone

from paper.ingestion.clients import (
    BlueskyMetricsClient,
    GithubMetricsClient,
    XMetricsClient,
)
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
        x_metrics_client: XMetricsClient,
    ):
        """
        Constructor.

        Args:
            github_metrics_client: Client for fetching GitHub metrics
            bluesky_metrics_client: Client for fetching Bluesky metrics
            x_metrics_client: Client for fetching X (Twitter) metrics
        """
        self.github_metrics_client = github_metrics_client
        self.bluesky_metrics_client = bluesky_metrics_client
        self.x_metrics_client = x_metrics_client

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
            result = self.x_metrics_client.get_metrics(
                terms,
                external_source=paper.external_source,
                hub_slugs=hub_slugs,
            )

            if result is None:
                logger.info(f"No X posts found for paper {paper.id}")
                return EnrichmentResult(status="not_found", reason="no_x_posts")

            self._update_paper_metrics(paper, {"x": result})

            # Save individual X posts to the database
            posts = result.get("posts", [])
            if posts:
                self._save_x_posts(paper, posts)

            logger.info(
                f"Successfully saved {result['post_count']} X posts for paper {paper.id}."
            )

            return EnrichmentResult(
                status="success",
                metrics={"x": result},
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

        for post_data in posts:
            post_id = post_data.get("id")
            if not post_id:
                continue

            # Parse posted_date datetime
            posted_date = None
            created_at_str = post_data.get("created_at")
            if created_at_str:
                try:
                    posted_date = date_parser.parse(created_at_str)
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse created_at: {created_at_str}")

            # Use update_or_create to handle duplicates
            XPost.objects.update_or_create(
                paper=paper,
                post_id=post_id,
                defaults={
                    "author_id": post_data.get("author_id"),
                    "text": post_data.get("text", ""),
                    "posted_date": posted_date,
                    "like_count": post_data.get("like_count", 0),
                    "repost_count": post_data.get("repost_count", 0),
                    "reply_count": post_data.get("reply_count", 0),
                    "quote_count": post_data.get("quote_count", 0),
                    "impression_count": post_data.get("impression_count", 0),
                },
            )
