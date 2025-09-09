"""
BioRxiv data mapper for transforming API responses to Paper model format.

Maps BioRxiv/MedRxiv paper records to ResearchHub Paper model fields.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

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
                logger.warning(
                    f"Missing required field '{field}' in record {record.get('doi', 'unknown')}"
                )
                return False

        # Validate date format
        try:
            datetime.strptime(record["date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(
                f"Invalid date format in record {record['doi']}: {record['date']}"
            )
            return False

        # Validate DOI format (basic check)
        doi = record["doi"]
        if not doi.startswith("10.1101/"):
            logger.warning(f"Unexpected DOI format: {doi}")
            # Don't skip, but log warning

        # Check for minimum content
        if len(record.get("title", "")) < 10:
            logger.warning(f"Title too short for record {doi}")
            return False

        if len(record.get("abstract", "")) < 50:
            logger.warning(f"Abstract too short or missing for record {doi}")
            # Don't skip abstracts that are missing, some papers may not have them

        return True

    def map_to_paper(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map BioRxiv record to Paper model fields.

        Args:
            record: BioRxiv paper record

        Returns:
            Dictionary with Paper model fields
        """
        # Extract basic fields
        doi = record.get("doi", "")
        version = record.get("version")

        # Build Paper model fields
        paper_data = {
            # Core identifiers
            "doi": doi,
            "external_source": record.get("server", "biorxiv").lower(),
            # Title and content
            "title": record.get("title", ""),
            "paper_title": record.get("title", ""),
            "abstract": record.get("abstract"),
            # Dates
            "paper_publish_date": self._parse_date(record.get("date")),
            # Authors
            "raw_authors": self._extract_authors(record.get("authors", "")),
            # Categories/subjects
            "categories": self._extract_categories(record.get("category")),
            # License and access
            "pdf_license": record.get("license"),
            "is_open_access": True,  # BioRxiv is open access
            "oa_status": "gold",  # Gold open access for preprints
            # External metadata
            "external_metadata": {
                "biorxiv_doi": doi,
                "version": version,
                "server": record.get("server", "biorxiv"),
                "category": record.get("category"),
                "published": record.get("published"),
                "jatsxml": record.get("jatsxml"),
            },
            # Status flags
            "retrieved_from_external_source": True,
        }

        # Add computed URLs if DOI and version exist
        if doi and version:
            paper_data["pdf_url"] = self._compute_pdf_url(doi, version)
            paper_data["url"] = self._compute_html_url(doi, version)

        # Add any additional metadata fields
        if record.get("published"):
            paper_data["external_metadata"]["published_date"] = record["published"]

        return paper_data

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

    def _extract_categories(self, category: Optional[str]) -> List[str]:
        """
        Extract categories from BioRxiv category field.

        Args:
            category: Category string from BioRxiv

        Returns:
            List of category strings
        """
        if not category:
            return []

        # BioRxiv categories are single strings
        # Could be expanded to map to ResearchHub hubs
        return [category]

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

    def map_to_author(self, author_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map author data to ResearchHub Author model fields.

        Args:
            author_data: Author data from BioRxiv

        Returns:
            Dictionary with Author model fields
        """
        return {
            "first_name": author_data.get("first_name", ""),
            "last_name": author_data.get("last_name", ""),
            "middle_name": author_data.get("middle_name", ""),
            "raw_name": author_data.get("raw_name", ""),
            "affiliations": author_data.get("affiliations", []),
        }
