"""
Paper ingestion service for processing raw responses and saving papers with authors.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

from .exceptions import IngestionError
from .mappers import BioRxivMapper

logger = logging.getLogger(__name__)


class PaperIngestionService:
    """Service for ingesting papers from external sources."""

    def __init__(self):
        """Initialize the ingestion service with available mappers."""
        self.mappers = {
            "biorxiv": BioRxivMapper(),
            "medrxiv": BioRxivMapper(),  # MedRxiv uses same format as BioRxiv
        }

    def process_raw_response(
        self, raw_data: List[Dict[str, Any]], source: str, save: bool = True
    ) -> Tuple[List[Paper], List[Author]]:
        """
        Process raw API response data into papers and authors.

        Args:
            raw_data: List of raw paper records from external API
            source: Source identifier (e.g., 'biorxiv', 'medrxiv')
            save: Whether to save to database (default True)

        Returns:
            Tuple of (papers, authors) lists

        Raises:
            IngestionError: If source mapper not found or processing fails
        """
        if source not in self.mappers:
            raise IngestionError(f"No mapper found for source: {source}")

        mapper = self.mappers[source]
        papers = []
        authors = []

        for record in raw_data:
            try:
                # Validate record
                if not mapper.validate(record):
                    logger.warning(
                        f"Skipping invalid record: {record.get('doi', 'unknown')}"
                    )
                    continue

                # Map to paper
                paper = mapper.map_to_paper(record)

                # Extract and map authors
                record_authors = []
                if hasattr(paper, "raw_authors") and paper.raw_authors:
                    for author_data in paper.raw_authors:
                        author = mapper.map_to_author(author_data)
                        record_authors.append(author)

                if save:
                    saved_paper, saved_authors = self._save_paper_with_authors(
                        paper, record_authors
                    )
                    papers.append(saved_paper)
                    authors.extend(saved_authors)
                else:
                    papers.append(paper)
                    authors.extend(record_authors)

            except Exception as e:
                logger.error(
                    f"Error processing record {record.get('doi', 'unknown')}: {e}"
                )
                continue

        return papers, authors

    def _save_paper_with_authors(
        self, paper: Paper, authors: List[Author]
    ) -> Tuple[Paper, List[Author]]:
        """
        Save paper and authors in a transaction.

        Args:
            paper: Paper instance to save
            authors: List of Author instances to save

        Returns:
            Tuple of (saved_paper, saved_authors)
        """
        with transaction.atomic():
            # Check if paper already exists by DOI
            existing_paper = None
            if paper.doi:
                existing_paper = Paper.objects.filter(doi=paper.doi).first()

            if existing_paper:
                return existing_paper, []

            # Save paper
            paper.save()

            # Save authors and create authorships
            saved_authors = []
            for i, author in enumerate(authors):
                # Try to find existing author by name
                existing_author = self._find_or_create_author(author)
                saved_authors.append(existing_author)

                # Create authorship relationship
                # Determine position based on author index
                if i == 0:
                    position = Authorship.FIRST_AUTHOR_POSITION
                elif i == len(authors) - 1 and len(authors) > 1:
                    position = Authorship.LAST_AUTHOR_POSITION
                else:
                    position = Authorship.MIDDLE_AUTHOR_POSITION

                Authorship.objects.create(
                    paper=paper,
                    author=existing_author,
                    author_position=position,
                    is_corresponding=False,  # Could be enhanced based on data
                    raw_author_name=getattr(author, "_raw_name", None),
                )

            return paper, saved_authors

    def _find_or_create_author(self, author: Author) -> Author:
        """
        Find existing author or create new one.

        Args:
            author: Author instance with name information

        Returns:
            Existing or newly created Author instance
        """
        # Look for existing author by first and last name
        existing_author = Author.objects.filter(
            first_name__iexact=author.first_name, last_name__iexact=author.last_name
        ).first()

        if existing_author:
            return existing_author

        # Create new author
        author.save()
        return author
