"""
Paper ingestion service for processing and saving papers from external sources.

This service takes raw responses from ingestion clients, maps them to Paper models,
and handles the saving process with proper validation and error handling.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction

from institution.models import Institution
from paper.ingestion.constants import IngestionSource
from paper.ingestion.mappers import BaseMapper
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

logger = logging.getLogger(__name__)


class PaperIngestionService:
    """
    Service for ingesting papers from external sources.

    This service processes raw responses from various ingestion clients,
    maps them to Paper model instances, and saves them to the database.
    """

    def __init__(self, mappers: Dict[IngestionSource, BaseMapper]):
        """Constructor."""
        self._mappers = mappers

    def get_mapper(self, source: IngestionSource) -> BaseMapper:
        """
        Get or create a mapper instance for the given source.

        Args:
            source: The ingestion source

        Returns:
            Mapper instance for the source

        Raises:
            ValueError: If the source is not supported
        """
        if source not in self._mappers:
            raise ValueError(f"Unsupported ingestion source: {source}")

        return self._mappers[source]

    def _create_authors_and_institutions(
        self,
        paper: Paper,
        record: Dict[str, Any],
        mapper: BaseMapper,
    ) -> Tuple[List[Author], List[Institution], List[Authorship]]:
        """
        Create authors, institutions, and their relationships for a paper.

        Args:
            paper: Saved Paper instance
            record: Original source record
            mapper: Mapper instance for the source

        Returns:
            Tuple of (created authors, created institutions, created authorships)
        """
        created_authors = []
        created_institutions = []
        created_authorships = []

        # Get model instances from mapper
        author_models = mapper.map_to_authors(record)
        institution_models = mapper.map_to_institutions(record)

        # Save or find existing institutions
        saved_institutions = {}  # Map ror_id to saved Institution
        for inst_model in institution_models:
            if not inst_model.ror_id:
                continue

            try:
                # Try to find existing institution by ROR ID
                existing_inst = Institution.objects.filter(
                    ror_id=inst_model.ror_id
                ).first()

                if existing_inst:
                    saved_institutions[inst_model.ror_id] = existing_inst
                else:
                    # Save new institution
                    inst_model.save()
                    created_institutions.append(inst_model)
                    saved_institutions[inst_model.ror_id] = inst_model
                    logger.info(
                        f"Created institution: {inst_model.display_name} "
                        f"with ROR ID: {inst_model.ror_id}"
                    )

            except Exception as e:
                logger.error(f"Failed to save institution: {e}")

        # Save or find existing authors
        saved_authors = {}  # Map orcid_id to saved Author
        for author_model in author_models:
            if not author_model.orcid_id:
                continue

            try:
                # Try to find existing author by ORCID ID
                existing_author = Author.objects.filter(
                    orcid_id=author_model.orcid_id
                ).first()

                if existing_author:
                    saved_authors[author_model.orcid_id] = existing_author
                else:
                    # Save new author
                    author_model.save()
                    created_authors.append(author_model)
                    saved_authors[author_model.orcid_id] = author_model
                    logger.info(
                        f"Created author: {author_model.first_name} {author_model.last_name} "
                        f"with ORCID: {author_model.orcid_id}"
                    )

            except Exception as e:
                logger.error(f"Failed to save author: {e}")

        # Get authorship models from mapper and save them
        authorship_models = mapper.map_to_authorships(paper, record)
        for authorship_model in authorship_models:
            # Update authorship with saved author instance
            if authorship_model.author and authorship_model.author.orcid_id:
                saved_author = saved_authors.get(authorship_model.author.orcid_id)
                if not saved_author:
                    continue  # Skip if author wasn't saved
                authorship_model.author = saved_author

            try:
                # Check if authorship already exists
                existing_authorship = Authorship.objects.filter(
                    paper=paper, author=authorship_model.author
                ).first()

                if not existing_authorship:
                    # Save new authorship
                    authorship_model.save()
                    created_authorships.append(authorship_model)

                    # Add institutions (many-to-many relationship)
                    if hasattr(authorship_model, "_institutions_to_add"):
                        for inst in authorship_model._institutions_to_add:
                            if inst.ror_id in saved_institutions:
                                authorship_model.institutions.add(
                                    saved_institutions[inst.ror_id]
                                )

                    logger.info(
                        f"Created authorship: {authorship_model.author.last_name} -> {paper.title[:50]}"
                    )

            except Exception as e:
                logger.error(f"Failed to create authorship: {e}")

        return created_authors, created_institutions, created_authorships

    def ingest_papers(
        self,
        raw_response: List[Dict[str, Any]],
        source: IngestionSource,
        validate: bool = True,
    ) -> Tuple[List[Paper], List[Dict[str, Any]]]:
        """
        Process and save papers from raw ingestion client response.

        Args:
            raw_response: List of raw paper records from the ingestion client
            source: The source of the papers (e.g., ArXiv, BioRxiv)
            validate: Whether to validate records before processing

        Returns:
            Tuple of (successfully processed papers, failed records with error info)
        """
        if not raw_response:
            logger.info("No papers to ingest")
            return [], []

        logger.info(
            f"Starting ingestion of {len(raw_response)} papers from {source.value}"
        )

        # Get the appropriate mapper
        try:
            mapper = self.get_mapper(source)
        except ValueError as e:
            logger.error(f"Failed to get mapper: {e}")
            return [], [{"error": str(e), "records": raw_response}]

        # Process papers
        successful_papers = []
        failed_records = []

        for record in raw_response:
            try:
                # Validate record if requested
                if validate and not mapper.validate(record):
                    failed_records.append(
                        {
                            "record": record,
                            "error": "Validation failed",
                            "id": record.get("id", "unknown"),
                        }
                    )
                    continue

                # Map to Paper model
                paper = mapper.map_to_paper(record)

                if not paper:
                    failed_records.append(
                        {
                            "record": record,
                            "error": "Mapper returned None",
                            "id": record.get("id", "unknown"),
                        }
                    )
                    continue

                paper = self._save_paper(paper)

                # Create hubs
                hubs = mapper.map_to_hubs(record)
                if hubs:
                    paper.unified_document.hubs.add(*hubs)

                # Create authors and institutions after paper is saved
                if paper and paper.id:
                    try:
                        authors, institutions, authorships = (
                            self._create_authors_and_institutions(paper, record, mapper)
                        )
                        logger.debug(
                            f"Created {len(authors)} authors, "
                            f"{len(institutions)} institutions, and "
                            f"{len(authorships)} authorships for paper {paper.id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to create authors/institutions for paper {paper.id}: {e}"
                        )

                successful_papers.append(paper)

            except Exception as e:
                logger.error(
                    f"Failed to process paper {record.get('id', 'unknown')}: {e}",
                    exc_info=True,
                )
                failed_records.append(
                    {
                        "record": record,
                        "error": str(e),
                        "id": record.get("id", "unknown"),
                    }
                )

        # Log results
        logger.info(
            f"Ingestion complete: {len(successful_papers)} successful, "
            f"{len(failed_records)} failed"
        )

        return successful_papers, failed_records

    def _trigger_pdf_download_if_needed(
        self, paper: Paper, pdf_url_changed: bool
    ) -> None:
        """
        Trigger PDF download if conditions are met.

        Args:
            paper: The saved Paper instance
            pdf_url_changed: Whether the PDF URL changed (for updates) or is new
        """
        # Trigger PDF download if:
        # - Paper has a PDF URL
        # - Either paper has no file yet OR the PDF URL changed (new version)
        if paper.pdf_url and (not paper.file or pdf_url_changed):
            from paper.tasks import download_pdf

            download_pdf.apply_async((paper.id,), priority=5)
            logger.info(f"Queued PDF download for paper {paper.id}")

    def _save_paper(
        self,
        paper: Paper,
    ) -> Paper:
        """
        Save or update a paper in the database, and trigger PDF download if needed.

        Args:
            paper: Paper model instance to save

        Returns:
            Saved Paper instance

        Raises:
            Exception: If save fails
        """
        with transaction.atomic():
            # Check if paper exists by DOI or URL
            existing_paper = None
            if paper.doi:
                existing_paper = Paper.objects.filter(doi=paper.doi).first()
            if not existing_paper and paper.url:
                existing_paper = Paper.objects.filter(url=paper.url).first()

            if existing_paper:
                # Update existing paper
                logger.info(
                    f"Updating existing paper {existing_paper.id} "
                    f"(DOI: {paper.doi}, URL: {paper.url})"
                )
                paper, pdf_url_changed = self._update_paper(existing_paper, paper)
                self._trigger_pdf_download_if_needed(
                    paper, pdf_url_changed=pdf_url_changed
                )
                return paper

            # Save new paper
            paper.save()
            logger.info(f"Saved new paper: {paper.id} - {paper.title}")
            self._trigger_pdf_download_if_needed(paper, pdf_url_changed=True)
            return paper

    def _update_paper(
        self, existing_paper: Paper, new_paper: Paper
    ) -> Tuple[Paper, bool]:
        """
        Update an existing paper with new data.

        Args:
            existing_paper: The existing Paper instance in the database
            new_paper: The new Paper instance with updated data

        Returns:
            Tuple of (Updated Paper instance, whether PDF URL changed)
        """
        # Track if PDF URL changed (for re-downloading updated PDFs)
        pdf_url_changed = (
            new_paper.pdf_url and existing_paper.pdf_url != new_paper.pdf_url
        )
        # Fields to update (exclude ID and creation timestamps)
        update_fields = [
            "title",
            "paper_title",
            "abstract",
            "paper_publish_date",
            "raw_authors",
            "external_source",
            "pdf_license",
            "pdf_license_url",
            "pdf_url",
            "url",
            "is_open_access",
            "oa_status",
        ]

        # Update fields
        for field in update_fields:
            if hasattr(new_paper, field):
                new_value = getattr(new_paper, field)
                # Only update if new value is not None/empty
                if new_value:
                    setattr(existing_paper, field, new_value)

        # Set DOI if existing paper doesn't have one
        if not existing_paper.doi and new_paper.doi:
            existing_paper.doi = new_paper.doi
            update_fields.append("doi")

        if new_paper.external_metadata:
            if existing_paper.external_metadata is None:
                existing_paper.external_metadata = {}
            existing_paper.external_metadata.update(new_paper.external_metadata)
            update_fields.append("external_metadata")

        existing_paper.save(update_fields=update_fields)
        return existing_paper, pdf_url_changed

    def ingest_single_paper(
        self,
        raw_record: Dict[str, Any],
        source: IngestionSource,
        validate: bool = True,
    ) -> Optional[Paper]:
        """
        Process and save a single paper from raw ingestion client response.

        Args:
            raw_record: Raw paper record from the ingestion client
            source: The source of the paper
            validate: Whether to validate the record before processing

        Returns:
            Processed Paper instance or None if failed
        """
        papers, failures = self.ingest_papers(
            [raw_record],
            source,
            validate=validate,
        )

        if papers:
            return papers[0]
        elif failures:
            logger.error(f"Failed to ingest paper: {failures[0].get('error')}")
            return None

        return None
