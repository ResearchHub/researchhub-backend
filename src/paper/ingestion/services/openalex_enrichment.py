import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

from django.db import transaction
from django.utils import timezone

from hub.models import Hub
from institution.models import Institution
from paper.ingestion.clients.enrichment.openalex import OpenAlexClient
from paper.ingestion.mappers import OpenAlexMapper
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Result of enriching a single paper with OpenAlex data."""

    status: str  # "success", "not_found", "skipped", or "error"
    license: Optional[str] = None
    license_url: Optional[str] = None
    reason: Optional[str] = None
    authors_created: int = 0
    authors_updated: int = 0
    institutions_created: int = 0
    institutions_updated: int = 0
    authorships_created: int = 0
    hubs_created: int = 0


@dataclass
class BatchEnrichmentResult:
    """Result of enriching multiple papers with OpenAlex data."""

    total: int
    success_count: int
    not_found_count: int
    error_count: int
    total_authors_created: int = 0
    total_authors_updated: int = 0
    total_institutions_created: int = 0
    total_institutions_updated: int = 0
    total_authorships_created: int = 0
    total_hubs_created: int = 0


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
        Fetch OpenAlex data for the given paper and update its license fields,
        authors, institutions, and authorships.

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
                    f"No OpenAlex data found for paper {paper.id} "
                    f"(DOI: {paper.doi})"
                )
                return EnrichmentResult(status="not_found", reason="no_openalex_data")

            # Map the OpenAlex data to a Paper instance to extract all fields
            raw_data = openalex_data.get("raw_data", {})
            mapped_paper = self.openalex_mapper.map_to_paper(raw_data)

            # Track statistics
            authors_created = 0
            authors_updated = 0
            institutions_created = 0
            institutions_updated = 0
            authorships_created = 0
            hubs_created = 0

            # Process in a transaction
            with transaction.atomic():
                # Process license data if available and not already present
                license_updated = False
                citations_updated = False
                update_fields = []

                if mapped_paper.pdf_url and mapped_paper.pdf_license:
                    # Only update if both required fields are missing (all-or-nothing)
                    if not (paper.pdf_url and paper.pdf_license):
                        update_fields = ["pdf_url", "pdf_license"]

                        paper.pdf_license = mapped_paper.pdf_license
                        paper.pdf_url = mapped_paper.pdf_url

                        # pdf_license_url is optional
                        if mapped_paper.pdf_license_url:
                            paper.pdf_license_url = mapped_paper.pdf_license_url
                            update_fields.append("pdf_license_url")

                        license_updated = True
                    else:
                        logger.debug(
                            f"Paper {paper.id} already has license data, "
                            f"skipping license update"
                        )
                else:
                    logger.debug(
                        f"Missing license data in OpenAlex for paper {paper.id} "
                        f"(has_pdf_url={bool(mapped_paper.pdf_url)}, "
                        f"has_license={bool(mapped_paper.pdf_license)})"
                    )

                # Update citations if available
                if mapped_paper.citations is not None:
                    paper.citations = mapped_paper.citations
                    update_fields = update_fields + ["citations"]
                    citations_updated = True

                if update_fields:
                    paper.save(update_fields=update_fields)

                # Always process authors, institutions, and authorships
                authors_created, authors_updated = self.process_authors(
                    paper, openalex_data
                )

                institutions_created, institutions_updated = self.process_institutions(
                    paper, openalex_data
                )

                authorships_created = self.process_authorships(paper, openalex_data)

                hubs_created = self.process_hubs(paper, openalex_data)

            logger.info(
                f"Successfully enriched paper {paper.id}: "
                f"license_updated={license_updated}, "
                f"citations_updated={citations_updated}, "
                f"{authors_created} authors created, "
                f"{authors_updated} authors updated, "
                f"{institutions_created} institutions created, "
                f"{institutions_updated} institutions updated, "
                f"{authorships_created} authorships created, "
                f"{hubs_created} hubs created"
            )

            return EnrichmentResult(
                status="success",
                license=paper.pdf_license,
                license_url=paper.pdf_license_url,
                authors_created=authors_created,
                authors_updated=authors_updated,
                institutions_created=institutions_created,
                institutions_updated=institutions_updated,
                authorships_created=authorships_created,
                hubs_created=hubs_created,
            )

        except Exception as e:
            logger.error(
                f"Error enriching paper {paper.id} (DOI: {paper.doi}): {str(e)}",
                exc_info=True,
            )
            return EnrichmentResult(status="error", reason=str(e))

    def process_authors(self, paper: Paper, openalex_data: dict) -> tuple[int, int]:
        """
        Process authors from OpenAlex data and create/update Author records.

        Args:
            paper: Paper instance
            openalex_data: OpenAlex work record

        Returns:
            Tuple of (authors_created, authors_updated)
        """
        authors_created = 0
        authors_updated = 0

        raw_data = openalex_data.get("raw_data", {})
        author_instances = self.openalex_mapper.map_to_authors(raw_data)

        for author_instance in author_instances:
            try:
                # Prepare defaults for creation
                defaults = {
                    "first_name": author_instance.first_name,
                    "last_name": author_instance.last_name,
                    "orcid_id": author_instance.orcid_id,
                    "created_source": getattr(
                        author_instance, "created_source", Author.SOURCE_OPENALEX
                    ),
                }

                _, created = Author.objects.update_or_create(
                    openalex_ids=author_instance.openalex_ids, defaults=defaults
                )

                if created:
                    authors_created += 1
                else:
                    authors_updated += 1

            except Exception as e:
                logger.error(
                    f"Error processing author for paper {paper.id}: {str(e)}",
                    exc_info=True,
                )

        return authors_created, authors_updated

    def process_institutions(
        self, paper: Paper, openalex_data: dict
    ) -> tuple[int, int]:
        """
        Process institutions from OpenAlex data and create/update Institution records.

        Args:
            paper: Paper instance
            openalex_data: OpenAlex work record

        Returns:
            Tuple of (institutions_created, institutions_updated)
        """
        institutions_created = 0
        institutions_updated = 0

        raw_data = openalex_data.get("raw_data", {})
        institution_instances = self.openalex_mapper.map_to_institutions(raw_data)

        for institution_instance in institution_instances:
            if not institution_instance.ror_id:
                continue

            try:
                # Prepare fields to update/create
                defaults = {
                    "display_name": institution_instance.display_name,
                    "country_code": institution_instance.country_code,
                    "openalex_id": institution_instance.openalex_id,
                    "ror_id": institution_instance.ror_id,
                    "type": institution_instance.type,
                    "associated_institutions": getattr(
                        institution_instance, "associated_institutions", []
                    )
                    or [],
                }

                _, created = Institution.objects.update_or_create(
                    openalex_id=institution_instance.openalex_id, defaults=defaults
                )

                if created:
                    institutions_created += 1
                else:
                    institutions_updated += 1

            except Exception as e:
                logger.error(
                    f"Error processing institution for paper {paper.id}: {str(e)}",
                    exc_info=True,
                )

        return institutions_created, institutions_updated

    def process_authorships(self, paper: Paper, openalex_data: dict) -> int:
        """
        Process authorships from OpenAlex data and create Authorship records.

        Args:
            paper: Paper instance
            openalex_data: OpenAlex work record

        Returns:
            Number of authorships created
        """
        authorships_created = 0

        raw_data = openalex_data.get("raw_data", {})
        authorship_instances = self.openalex_mapper.map_to_authorships(paper, raw_data)

        for authorship_instance in authorship_instances:
            try:
                # Get the author by OpenAlex ID
                author_openalex_id = getattr(
                    authorship_instance, "_author_openalex_id", None
                )
                if not author_openalex_id:
                    continue

                author = Author.objects.filter(
                    openalex_ids__contains=[author_openalex_id]
                ).first()
                if not author:
                    logger.warning(
                        f"Author with OpenAlex ID {author_openalex_id} not found for paper {paper.id}"
                    )
                    continue

                # Set the author on the authorship
                authorship_instance.author = author

                # Check if authorship already exists
                existing_authorship = Authorship.objects.filter(
                    paper=paper, author=author
                ).first()

                if existing_authorship:
                    logger.debug(
                        f"Authorship already exists for paper {paper.id} "
                        f"and author {author.id}"
                    )
                    continue

                # Save the authorship
                authorship_instance.save()

                # Link institutions if available
                institution_openalex_ids = getattr(
                    authorship_instance, "_institution_openalex_ids", []
                )
                if institution_openalex_ids:
                    institutions = Institution.objects.filter(
                        openalex_id__in=institution_openalex_ids
                    )
                    authorship_instance.institutions.set(institutions)

                authorships_created += 1

            except Exception as e:
                logger.error(
                    f"Error processing authorship for paper {paper.id}: {str(e)}",
                    exc_info=True,
                )

        return authorships_created

    def process_hubs(self, paper: Paper, openalex_data: dict) -> int:
        """
        Process hubs from OpenAlex data, create Hub instances, and assign it to the given paper.

        Args:
            paper: Paper instance
            openalex_data: OpenAlex work record

        Returns:
            Number of hubs created
        """
        hubs_created = 0

        raw_data = openalex_data.get("raw_data", {})
        hubs = self.openalex_mapper.map_to_hubs(raw_data)

        for hub in hubs:
            try:
                hub, created = Hub.objects.get_or_create(name=hub.name)
                if created:
                    hubs_created += 1

                paper.unified_document.hubs.add(hub)

            except Exception as e:
                logger.error(
                    f"Error processing hub for paper {paper.id}: {str(e)}",
                    exc_info=True,
                )

        return hubs_created

    def enrich_papers_batch(self, paper_ids: List[int]) -> BatchEnrichmentResult:
        """
        Enrich multiple papers with OpenAlex data, including license info,
        authors, institutions, and authorships.

        Args:
            paper_ids: List of paper IDs to enrich

        Returns:
            BatchEnrichmentResult with summary statistics
        """
        total = len(paper_ids)
        success_count = 0
        not_found_count = 0
        error_count = 0
        total_authors_created = 0
        total_authors_updated = 0
        total_institutions_created = 0
        total_institutions_updated = 0
        total_authorships_created = 0
        total_hubs_created = 0

        for paper_id in paper_ids:
            try:
                paper = Paper.objects.get(id=paper_id)
                result = self.enrich_paper_with_openalex(paper)

                if result.status == "success":
                    success_count += 1
                    total_authors_created += result.authors_created
                    total_authors_updated += result.authors_updated
                    total_institutions_created += result.institutions_created
                    total_institutions_updated += result.institutions_updated
                    total_authorships_created += result.authorships_created
                    total_hubs_created += result.hubs_created
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
            total_authors_created=total_authors_created,
            total_authors_updated=total_authors_updated,
            total_institutions_created=total_institutions_created,
            total_institutions_updated=total_institutions_updated,
            total_authorships_created=total_authorships_created,
            total_hubs_created=total_hubs_created,
        )
