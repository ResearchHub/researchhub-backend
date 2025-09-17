"""
Paper ingestion service for processing and saving papers from external sources.

This service takes raw responses from ingestion clients, maps them to Paper models,
and handles the saving process with proper validation and error handling.
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type

from django.db import transaction

from paper.ingestion.mappers import (
    ArXivMapper,
    BaseMapper,
    BioRxivMapper,
    ChemRxivMapper,
)
from paper.models import Paper

logger = logging.getLogger(__name__)


class IngestionSource(Enum):
    """Supported ingestion sources."""

    ARXIV = "arxiv"
    BIORXIV = "biorxiv"
    CHEMRXIV = "chemrxiv"


class PaperIngestionService:
    """
    Service for ingesting papers from external sources.

    This service processes raw responses from various ingestion clients,
    maps them to Paper model instances, and saves them to the database.
    """

    # Mapping of sources to their respective mapper classes
    MAPPER_REGISTRY: Dict[IngestionSource, Type[BaseMapper]] = {
        IngestionSource.ARXIV: ArXivMapper,
        IngestionSource.BIORXIV: BioRxivMapper,
        IngestionSource.CHEMRXIV: ChemRxivMapper,
    }

    def __init__(self):
        """Initialize the ingestion service."""
        self._mappers: Dict[IngestionSource, BaseMapper] = {}

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
        if source not in self.MAPPER_REGISTRY:
            raise ValueError(f"Unsupported ingestion source: {source}")

        # Create mapper instance if not cached
        if source not in self._mappers:
            mapper_class = self.MAPPER_REGISTRY[source]
            self._mappers[source] = mapper_class()

        return self._mappers[source]

    def ingest_papers(
        self,
        raw_response: List[Dict[str, Any]],
        source: IngestionSource,
        validate: bool = True,
        save_to_db: bool = True,
        update_existing: bool = False,
    ) -> Tuple[List[Paper], List[Dict[str, Any]]]:
        """
        Process and save papers from raw ingestion client response.

        Args:
            raw_response: List of raw paper records from the ingestion client
            source: The source of the papers (e.g., ArXiv, BioRxiv)
            validate: Whether to validate records before processing
            save_to_db: Whether to save the papers to the database
            update_existing: Whether to update existing papers (by DOI)

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

                # Save to database if requested
                if save_to_db:
                    paper = self._save_paper(paper, update_existing)

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

    def _save_paper(self, paper: Paper, update_existing: bool = False) -> Paper:
        """
        Save or update a paper in the database.

        Args:
            paper: Paper model instance to save
            update_existing: Whether to update if paper exists (by DOI)

        Returns:
            Saved Paper instance

        Raises:
            Exception: If save fails
        """
        with transaction.atomic():
            # Check if paper exists by DOI
            if paper.doi:
                existing_paper = Paper.objects.filter(doi=paper.doi).first()

                if existing_paper:
                    if update_existing:
                        # Update existing paper
                        logger.info(f"Updating existing paper with DOI {paper.doi}")
                        return self._update_paper(existing_paper, paper)
                    else:
                        logger.info(
                            f"Paper with DOI {paper.doi} already exists, skipping"
                        )
                        return existing_paper

            # Save new paper
            paper.save()
            logger.info(f"Saved new paper: {paper.id} - {paper.title}")
            return paper

    def _update_paper(self, existing_paper: Paper, new_paper: Paper) -> Paper:
        """
        Update an existing paper with new data.

        Args:
            existing_paper: The existing Paper instance in the database
            new_paper: The new Paper instance with updated data

        Returns:
            Updated Paper instance
        """
        # Fields to update (exclude ID and creation timestamps)
        update_fields = [
            "title",
            "paper_title",
            "abstract",
            "paper_publish_date",
            "raw_authors",
            "external_metadata",
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

        existing_paper.save(update_fields=update_fields)
        return existing_paper

    def ingest_single_paper(
        self,
        raw_record: Dict[str, Any],
        source: IngestionSource,
        validate: bool = True,
        save_to_db: bool = True,
        update_existing: bool = False,
    ) -> Optional[Paper]:
        """
        Process and save a single paper from raw ingestion client response.

        Args:
            raw_record: Raw paper record from the ingestion client
            source: The source of the paper
            validate: Whether to validate the record before processing
            save_to_db: Whether to save the paper to the database
            update_existing: Whether to update if paper exists

        Returns:
            Processed Paper instance or None if failed
        """
        papers, failures = self.ingest_papers(
            [raw_record],
            source,
            validate=validate,
            save_to_db=save_to_db,
            update_existing=update_existing,
        )

        if papers:
            return papers[0]
        elif failures:
            logger.error(f"Failed to ingest paper: {failures[0].get('error')}")
            return None

        return None
