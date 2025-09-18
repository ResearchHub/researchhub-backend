"""
BioRxiv data mapper for transforming API responses to Paper model format.

Maps BioRxiv/MedRxiv paper records to ResearchHub Paper model fields.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from hub.models import Hub
from institution.models import Institution
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

from .base import BaseMapper

logger = logging.getLogger(__name__)


class BioRxivMapper(BaseMapper):
    """Maps BioRxiv paper records to ResearchHub Paper model format."""

    BIOARXIV_HUB = Hub.objects.filter(
        slug="biorxiv", namespace=Hub.Namespace.JOURNAL
    ).first()

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
            # Status flags
            retrieved_from_external_source=True,
        )

        # Add computed URLs if DOI and version exist
        if doi and version:
            paper.pdf_url = self._compute_pdf_url(doi, version)
            paper.url = self._compute_html_url(doi, version)

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

    def map_to_authors(self, record: Dict[str, Any]) -> List[Author]:
        """
        Map BioRxiv record to author data.

        Note: BioRxiv doesn't provide ORCID IDs, so we return empty list
        to avoid creating duplicate authors without proper deduplication.
        """
        # Return empty list - we don't create authors without ORCID IDs
        return []

    def map_to_institutions(self, record: Dict[str, Any]) -> List[Institution]:
        """
        Map BioRxiv record to institution data.

        Note: BioRxiv doesn't provide ROR IDs for institutions,
        so we return empty list to avoid creating duplicate institutions.
        """
        # Return empty list - we don't create institutions without ROR IDs
        return []

    def map_to_authorships(
        self, paper: Paper, record: Dict[str, Any]
    ) -> List[Authorship]:
        """
        Map BioRxiv record to Authorship model instances.

        Note: BioRxiv doesn't provide ORCID IDs for authors,
        so we return empty list to avoid creating duplicate authorships.
        """
        # Return empty list - we don't create authorships without proper author IDs
        return []

    def map_to_hubs(self, paper: Paper, record: Dict[str, Any]) -> List[Hub]:
        """
        Map BioRxiv record to Hub (tag) model instances.

        Initially, this only returns the preprint server hub.
        """
        return [self.BIOARXIV_HUB] if self.BIOARXIV_HUB else []
