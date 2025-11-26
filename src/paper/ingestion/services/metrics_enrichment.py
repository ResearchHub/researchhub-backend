import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from paper.ingestion.clients import GithubMetricsClient
from paper.ingestion.clients.enrichment.altmetric import AltmetricClient
from paper.ingestion.mappers import AltmetricMapper
from paper.models import Paper

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Result of enriching a single paper with Altmetric metrics."""

    status: str  # "success", "not_found", "skipped", or "error"
    metrics: Optional[Dict[str, Any]] = None
    altmetric_score: Optional[float] = None
    reason: Optional[str] = None


@dataclass
class BatchEnrichmentResult:
    """Result of enriching multiple papers with Altmetric metrics."""

    total: int
    success_count: int
    not_found_count: int
    error_count: int


class PaperMetricsEnrichmentService:
    """
    Service for enriching papers with external metrics data.

    This service handles fetching metrics from Altmetric and updating
    the corresponding papers in the database.
    """

    def __init__(
        self,
        altmetric_client: AltmetricClient,
        altmetric_mapper: AltmetricMapper,
        github_metrics_client: GithubMetricsClient,
    ):
        """
        Constructor.

        Args:
            altmetric_client: Client for fetching Altmetric data
            altmetric_mapper: Mapper for transforming Altmetric data
            github_metrics_client: Client for fetching GitHub metrics
        """
        self.altmetric_client = altmetric_client
        self.altmetric_mapper = altmetric_mapper
        self.github_metrics_client = github_metrics_client

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
        if not paper.doi:
            logger.warning(f"Paper {paper.id} has no DOI, skipping GitHub enrichment")
            return EnrichmentResult(status="skipped", reason="no_doi")

        try:
            result = self.github_metrics_client.get_mentions(
                paper.doi, search_areas=["issues"]
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
            logger.error(f"Error fetching GitHub mentions for paper {paper.id}: {e}")
            return EnrichmentResult(status="error", reason=str(e))

    def enrich_paper_with_altmetric(self, paper: Paper) -> EnrichmentResult:
        """
        Fetch Altmetric metrics for the given paper and update its external_metadata.

        Args:
            paper: Paper instance to enrich

        Returns:
            EnrichmentResult with status and details
        """
        if not paper.doi:
            logger.warning(f"Paper {paper.id} has no DOI, skipping enrichment")
            return EnrichmentResult(status="skipped", reason="no_doi")

        try:
            # Fetch Altmetric data
            if paper.external_source == "arxiv":
                arxiv_id = (paper.external_metadata or {}).get("external_id")
                if not arxiv_id:
                    logger.warning(f"arXiv paper {paper.id} without arXiv ID, skipping")
                    return EnrichmentResult(status="skipped", reason="no_arxiv_id")
                altmetric_data = self.altmetric_client.fetch_by_arxiv_id(arxiv_id)
            else:
                altmetric_data = self.altmetric_client.fetch_by_doi(paper.doi)

            if not altmetric_data:
                logger.info(f"No Altmetric data found for paper {paper.id}")
                return EnrichmentResult(status="not_found", reason="no_altmetric_data")

            mapped_metrics = self.altmetric_mapper.map_metrics(altmetric_data)

            # Update paper's external_metadata
            self._update_paper_metrics(paper, mapped_metrics)

            logger.info(
                f"Successfully enriched paper {paper.id} with Altmetric metrics"
            )

            return EnrichmentResult(
                status="success",
                metrics=mapped_metrics,
                altmetric_score=mapped_metrics.get("score"),
            )

        except Exception as e:
            logger.error(
                f"Error enriching paper {paper.id} (DOI: {paper.doi}): {str(e)}",
                exc_info=True,
            )
            return EnrichmentResult(status="error", reason=str(e))

    def enrich_papers_batch(self, paper_ids: List[int]) -> BatchEnrichmentResult:
        """
        Enrich multiple papers with Altmetric metrics.

        Args:
            paper_ids: List of paper IDs to enrich

        Returns:
            BatchEnrichmentResult with summary statistics
        """
        total = len(paper_ids)
        success_count = 0
        not_found_count = 0
        error_count = 0

        for paper_id in paper_ids:
            try:
                paper = Paper.objects.get(id=paper_id)
                result = self.enrich_paper_with_altmetric(paper)

                if result.status == "success":
                    success_count += 1
                elif result.status in ["not_found", "skipped"]:
                    not_found_count += 1
                else:
                    error_count += 1

            except Paper.DoesNotExist:
                error_count += 1
                logger.error(f"Paper {paper_id} not found during enrichment")
            except Exception as e:
                error_count += 1
                logger.error(
                    f"Unexpected error processing paper {paper_id}: {str(e)}",
                    exc_info=True,
                )

        return BatchEnrichmentResult(
            total=total,
            success_count=success_count,
            not_found_count=not_found_count,
            error_count=error_count,
        )

    def _update_paper_metrics(self, paper: Paper, metrics: Dict[str, Any]) -> None:
        """
        Update paper's external_metadata with metrics while preserving existing metrics.

        New metrics are merged with existing metrics, allowing multiple enrichment
        sources (e.g., Altmetric and GitHub) to coexist without overwriting each other.
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
