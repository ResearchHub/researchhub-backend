"""
BioRxiv data mapper for transforming API responses to Paper model format.

Maps BioRxiv/MedRxiv paper records to ResearchHub Paper model fields.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from paper.models import Paper
from user.related_models.author_model import Author

from .base import BaseMapper

logger = logging.getLogger(__name__)


class BioRxivMapper(BaseMapper):
    """Maps BioRxiv paper records to ResearchHub Paper model format."""

    def validate(self, record: Dict[str, Any]) -> bool:
        """
        Validate a BioRxiv paper record has minimum required fields.

        Args:
            record: Paper record to validate

        Returns:
            True if valid, False if should be skipped
        """
        # Required fields from BioRxiv API
        required_fields = ["doi", "title", "authors", "date"]

        for field in required_fields:
            if not record.get(field):
                doi_str = record.get("doi", "unknown")
                logger.warning(f"Missing required field '{field}' in record {doi_str}")
                return False

        # Validate date format
        try:
            datetime.strptime(record["date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(
                f"Invalid date format in record {record['doi']}: {record['date']}"
            )
            return False

        return True

    def map_to_paper(self, record: Dict[str, Any]) -> Paper:
        """
        Map BioRxiv record to Paper model instance.

        Args:
            record: BioRxiv paper record

        Returns:
            Paper model instance (not saved to database)
        """
        # Extract basic fields
        doi = record.get("doi", "")
        version = record.get("version")

        # Extract and process authors first
        raw_authors = self._extract_authors(record.get("authors", ""))

        # Create Paper instance
        paper = Paper(
            # Core identifiers
            doi=doi,
            external_source=record.get("server", "biorxiv").lower(),
            # Title and content
            title=record.get("title", ""),
            paper_title=record.get("title", ""),
            abstract=record.get("abstract"),
            # Dates
            paper_publish_date=self._parse_date(record.get("date")),
            # Authors (JSON field)
            raw_authors=raw_authors,
            # License and access
            pdf_license=record.get("license"),
            is_open_access=True,  # BioRxiv is open access
            oa_status="gold",  # Gold open access for preprints
            # External metadata
            external_metadata={
                "biorxiv_doi": doi,
                "version": version,
                "server": record.get("server", "biorxiv"),
                "category": record.get("category"),
                "published": record.get("published"),
                "jatsxml": record.get("jatsxml"),
            },
            # Status flags
            retrieved_from_external_source=True,
        )

        # Add computed URLs if DOI and version exist
        if doi and version:
            paper.pdf_url = self._compute_pdf_url(doi, version)
            paper.url = self._compute_html_url(doi, version)

        # Add any additional metadata fields
        if record.get("published"):
            paper.external_metadata["published_date"] = record["published"]

        return paper

    def _parse_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Parse date string to Paper model format.

        Args:
            date_str: Date string in YYYY-MM-DD format

        Returns:
            Date string or None if invalid
        """
        if not date_str:
            return None

        try:
            # Validate and return in same format
            datetime.strptime(date_str, "%Y-%m-%d")
            return date_str
        except (ValueError, TypeError):
            logger.warning(f"Invalid date format: {date_str}")
            return None

    def _extract_authors(self, authors_str: str) -> List[Dict[str, Any]]:
        """
        Extract authors from BioRxiv author string.

        BioRxiv returns authors as a semicolon-separated string.

        Args:
            authors_str: Author string from BioRxiv

        Returns:
            List of author dictionaries
        """
        if not authors_str:
            return []

        authors = []
        for author_name in authors_str.split(";"):
            author_name = author_name.strip()
            if author_name:
                # Parse name into components
                name_parts = self._parse_author_name(author_name)
                authors.append(
                    {
                        "full_name": author_name,
                        "first_name": name_parts.get("first_name", ""),
                        "last_name": name_parts.get("last_name", ""),
                        "middle_name": name_parts.get("middle_name", ""),
                        "raw_name": author_name,
                    }
                )

        return authors

    def _parse_author_name(self, full_name: str) -> Dict[str, str]:
        """
        Parse author name into components.

        BioRxiv format is typically "Last Name, First Name"

        Args:
            full_name: Full author name

        Returns:
            Dictionary with first_name, middle_name, last_name
        """
        # Check if name contains a comma (Last, First format)
        if ", " in full_name:
            parts = full_name.split(", ", 1)
            last_name = parts[0]
            first_and_middle = parts[1] if len(parts) > 1 else ""

            # Split first and middle names
            first_parts = first_and_middle.split()
            if not first_parts:
                return {"first_name": "", "middle_name": "", "last_name": last_name}
            elif len(first_parts) == 1:
                return {
                    "first_name": first_parts[0],
                    "middle_name": "",
                    "last_name": last_name,
                }
            else:
                return {
                    "first_name": first_parts[0],
                    "middle_name": " ".join(first_parts[1:]),
                    "last_name": last_name,
                }

        # Fall back to space-separated format (First Middle Last)
        parts = full_name.split()

        if not parts:
            return {"first_name": "", "middle_name": "", "last_name": ""}

        if len(parts) == 1:
            return {"first_name": "", "middle_name": "", "last_name": parts[0]}

        if len(parts) == 2:
            return {"first_name": parts[0], "middle_name": "", "last_name": parts[1]}

        # Three or more parts
        return {
            "first_name": parts[0],
            "middle_name": " ".join(parts[1:-1]),
            "last_name": parts[-1],
        }

    def _compute_pdf_url(self, doi: str, version: str) -> str:
        """
        Compute PDF URL from DOI and version.

        Args:
            doi: DOI identifier
            version: Paper version number

        Returns:
            Full PDF URL
        """
        return f"https://www.biorxiv.org/content/{doi}v{version}.full.pdf"

    def _compute_html_url(self, doi: str, version: str) -> str:
        """
        Compute HTML URL from DOI and version.

        Args:
            doi: DOI identifier
            version: Paper version number

        Returns:
            Full HTML URL
        """
        return f"https://www.biorxiv.org/content/{doi}v{version}"

    def map_to_author(self, author_data: Dict[str, Any]) -> Author:
        """
        Map author data to ResearchHub Author model instance.

        Args:
            author_data: Author data from BioRxiv

        Returns:
            Author model instance (not saved to database)
        """
        # Create Author instance with available fields
        author = Author(
            first_name=author_data.get("first_name", ""),
            last_name=author_data.get("last_name", ""),
            # Source indicates this came from external ingestion
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        # Store additional data as attributes for optional processing
        # These aren't direct fields on the Author model
        author._middle_name = author_data.get("middle_name", "")
        author._raw_name = author_data.get("raw_name", "")
        author._affiliations = author_data.get("affiliations", [])

        return author
