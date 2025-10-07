import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.utils import timezone

from paper.ingestion.clients.openalex import OpenAlexClient
from paper.models import Paper

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Result of enriching a single paper with OpenAlex data."""

    status: str  # "success", "not_found", "skipped", or "error"
    license: Optional[str] = None
    license_url: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class BatchEnrichmentResult:
    """Result of enriching multiple papers with OpenAlex data."""

    total: int
    success_count: int
    not_found_count: int
    error_count: int


class PaperOpenAlexEnrichmentService:
    """
    Service for enriching papers with OpenAlex data.

    This service handles fetching data from OpenAlex and updating
    the corresponding papers in the database.
    """

    def __init__(self, openalex_client: OpenAlexClient):
        """
        Constructor.

        Args:
            openalex_client: Client for fetching OpenAlex data
        """
        self.openalex_client = openalex_client

    def get_recent_papers_with_dois(self, days: int) -> List[int]:
        """
        Query papers created in the last N days that have DOIs.

        Args:
            days: Number of days to look back

        Returns:
            List of paper IDs
        """
        date_threshold = timezone.now() - timedelta(days=days)
        paper_ids = (
            Paper.objects.filter(created_date__gte=date_threshold, doi__isnull=False)
            .exclude(doi="")
            .values_list("id", flat=True)
        )
        return list(paper_ids)

    def enrich_paper_with_openalex(self, paper: Paper) -> EnrichmentResult:
        """
        Fetch OpenAlex data for the given paper and update its license fields.

        Args:
            paper: Paper instance to enrich

        Returns:
            EnrichmentResult with status and details
        """
        if not paper.doi:
            logger.warning(f"Paper {paper.id} has no DOI, skipping enrichment")
            return EnrichmentResult(status="skipped", reason="no_doi")

        try:
            # Fetch OpenAlex data
            openalex_data = self.openalex_client.fetch_by_doi(paper.doi)

            if not openalex_data:
                logger.info(
                    f"No OpenAlex data found for paper {paper.id} (DOI: {paper.doi})"
                )
                return EnrichmentResult(status="not_found", reason="no_openalex_data")

            # Extract license information from the raw data
            raw_data = openalex_data.get("raw_data", {})
            license_info = self._extract_license_info(raw_data)

            if not license_info["license"] and not license_info["license_url"]:
                logger.info(
                    f"No license information found in OpenAlex data for paper {paper.id}"
                )
                return EnrichmentResult(
                    status="not_found", reason="no_license_in_openalex"
                )

            # Update paper's license fields
            self._update_paper_license(paper, license_info)

            logger.info(
                f"Successfully enriched paper {paper.id} with OpenAlex license data"
            )

            return EnrichmentResult(
                status="success",
                license=license_info["license"],
                license_url=license_info["license_url"],
            )

        except Exception as e:
            logger.error(
                f"Error enriching paper {paper.id} (DOI: {paper.doi}): {str(e)}",
                exc_info=True,
            )
            return EnrichmentResult(status="error", reason=str(e))

    def enrich_papers_batch(self, paper_ids: List[int]) -> BatchEnrichmentResult:
        """
        Enrich multiple papers with OpenAlex data.

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
                result = self.enrich_paper_with_openalex(paper)

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

    def _extract_license_info(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract license information from OpenAlex raw data.

        Args:
            raw_data: Raw OpenAlex work data

        Returns:
            Dictionary with 'license' and 'license_url' keys
        """
        license_info = {"license": None, "license_url": None}

        # Try to get license from best_oa_location first (most reliable)
        best_oa_location = raw_data.get("best_oa_location", {})
        if best_oa_location:
            license_info["license"] = best_oa_location.get("license")
            license_info["license_url"] = best_oa_location.get("license_id")

        # Fall back to primary_location if best_oa_location doesn't have license
        if not license_info["license"]:
            primary_location = raw_data.get("primary_location", {})
            if primary_location:
                license_info["license"] = primary_location.get("license")
                license_info["license_url"] = primary_location.get("license_id")

        # Fall back to top-level license field if still not found
        if not license_info["license"]:
            license_info["license"] = raw_data.get("license")

        return license_info

    def _update_paper_license(self, paper: Paper, license_info: Dict[str, Any]) -> None:
        """
        Update paper's license fields.

        Args:
            paper: Paper instance to update
            license_info: Dictionary with license and license_url
        """
        update_fields = []

        if license_info["license"]:
            paper.pdf_license = license_info["license"]
            update_fields.append("pdf_license")

        if license_info["license_url"]:
            paper.pdf_license_url = license_info["license_url"]
            update_fields.append("pdf_license_url")

        if update_fields:
            paper.save(update_fields=update_fields)
