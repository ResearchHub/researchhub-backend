import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from django.utils import timezone

from paper.ingestion.clients.openalex import OpenAlexClient
from paper.ingestion.mappers.openalex import OpenAlexMapper
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

    def __init__(
        self, openalex_client: OpenAlexClient, openalex_mapper: OpenAlexMapper
    ):
        """
        Constructor.

        Args:
            openalex_client: Client for fetching OpenAlex data
            openalex_mapper: Mapper for extracting data from OpenAlex records
        """
        self.openalex_client = openalex_client
        self.openalex_mapper = openalex_mapper

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

            # Map the OpenAlex data to a Paper instance to extract all fields
            raw_data = openalex_data.get("raw_data", {})
            mapped_paper = self.openalex_mapper.map_to_paper(raw_data)

            if not mapped_paper.pdf_url or not mapped_paper.pdf_license:
                logger.info(
                    f"Missing required license data in OpenAlex for paper {paper.id} "
                    f"(has_pdf_url={bool(mapped_paper.pdf_url)}, has_license={bool(mapped_paper.pdf_license)})"
                )
                return EnrichmentResult(
                    status="not_found", reason="incomplete_license_data"
                )

            # Only update if both required fields are missing (all-or-nothing)
            if paper.pdf_url and paper.pdf_license:
                logger.info(
                    f"Paper {paper.id} already has license data, skipping enrichment"
                )
                return EnrichmentResult(status="skipped", reason="already_has_data")

            update_fields = ["pdf_url", "pdf_license"]

            paper.pdf_license = mapped_paper.pdf_license

            paper.pdf_url = mapped_paper.pdf_url

            # pdf_license_url is optional
            if mapped_paper.pdf_license_url:
                paper.pdf_license_url = mapped_paper.pdf_license_url
                update_fields.append("pdf_license_url")

            paper.save(update_fields=update_fields)

            logger.info(
                f"Successfully enriched paper {paper.id} with OpenAlex license data"
            )

            return EnrichmentResult(
                status="success",
                license=paper.pdf_license,
                license_url=paper.pdf_license_url,
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
