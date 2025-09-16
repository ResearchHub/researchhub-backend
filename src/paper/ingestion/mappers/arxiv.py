"""
ArXiv data mapper for transforming API responses to Paper model format.

Maps ArXiv paper records to ResearchHub Paper model fields.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

from institution.models import Institution
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

from .base import BaseMapper

logger = logging.getLogger(__name__)


class ArXivMapper(BaseMapper):
    """Maps ArXiv paper records to ResearchHub Paper model format."""

    # XML namespaces used by ArXiv
    ATOM_NS = "{http://www.w3.org/2005/Atom}"
    ARXIV_NS = "{http://arxiv.org/schemas/atom}"
    OPENSEARCH_NS = "{http://a9.com/-/spec/opensearch/1.1/}"

    def _parse_xml_entry(self, raw_xml: str) -> Dict[str, Any]:
        """
        Parse raw XML entry into a dictionary.

        Args:
            raw_xml: Raw XML string for a single entry

        Returns:
            Dictionary with parsed fields
        """
        try:
            root = ET.fromstring(raw_xml)

            # Extract basic fields
            entry_data = {
                "id": self._get_text(root, f"{self.ATOM_NS}id"),
                "title": self._get_text(root, f"{self.ATOM_NS}title"),
                "summary": self._get_text(root, f"{self.ATOM_NS}summary"),
                "published": self._get_text(root, f"{self.ATOM_NS}published"),
                "updated": self._get_text(root, f"{self.ATOM_NS}updated"),
            }

            # Extract authors
            authors = []
            for author_elem in root.findall(f"{self.ATOM_NS}author"):
                author_data = {
                    "name": self._get_text(author_elem, f"{self.ATOM_NS}name")
                }
                # Check for affiliation
                affiliation = self._get_text(author_elem, f"{self.ARXIV_NS}affiliation")
                if affiliation:
                    author_data["affiliation"] = affiliation
                authors.append(author_data)
            entry_data["authors"] = authors

            # Extract categories
            categories = []
            for cat_elem in root.findall(f"{self.ATOM_NS}category"):
                term = cat_elem.get("term")
                if term:
                    categories.append(term)
            entry_data["categories"] = categories

            # Extract primary category
            primary_cat = root.find(f"{self.ARXIV_NS}primary_category")
            if primary_cat is not None:
                entry_data["primary_category"] = primary_cat.get("term", "")

            # Extract links
            links = {}
            for link_elem in root.findall(f"{self.ATOM_NS}link"):
                rel = link_elem.get("rel")
                href = link_elem.get("href")
                title = link_elem.get("title")

                if rel == "alternate":
                    links["alternate"] = href
                elif title == "pdf":
                    links["pdf"] = href
            entry_data["links"] = links

            # Extract optional fields
            entry_data["comment"] = self._get_text(root, f"{self.ARXIV_NS}comment")
            entry_data["journal_ref"] = self._get_text(
                root, f"{self.ARXIV_NS}journal_ref"
            )
            entry_data["doi"] = self._get_text(root, f"{self.ARXIV_NS}doi")

            return entry_data

        except ET.ParseError as e:
            logger.error(f"Failed to parse XML entry: {e}")
            return {}

    def _get_text(self, element: ET.Element, tag: str) -> Optional[str]:
        """
        Get text content from an XML element.

        Args:
            element: Parent element
            tag: Tag to find

        Returns:
            Text content or None
        """
        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None

    def validate(self, record: Dict[str, Any]) -> bool:
        """
        Validate an ArXiv paper record has minimum required fields.

        Args:
            record: Paper record to validate (may contain raw_xml)

        Returns:
            True if valid, False if should be skipped
        """
        # If record contains raw_xml, parse it first
        if "raw_xml" in record and not record.get("id"):
            parsed = self._parse_xml_entry(record["raw_xml"])
            record.update(parsed)

        # Required fields from ArXiv API
        required_fields = ["id", "title", "authors"]

        for field in required_fields:
            if not record.get(field):
                record_id = record.get("id", "unknown")
                logger.warning(
                    f"Missing required field '{field}' in record {record_id}"
                )
                return False

        # Validate at least one author exists
        if not record.get("authors") or len(record["authors"]) == 0:
            logger.warning(f"No authors found in record {record['id']}")
            return False

        # Validate published or updated date exists
        if not record.get("published") and not record.get("updated"):
            logger.warning(f"No published or updated date in record {record['id']}")
            return False

        return True

    def map_to_paper(self, record: Dict[str, Any]) -> Paper:
        """
        Map ArXiv record to Paper model instance.

        Args:
            record: ArXiv paper record (may contain raw_xml)

        Returns:
            Paper model instance (not saved to database)
        """
        # If record contains raw_xml, parse it first
        if "raw_xml" in record and not record.get("id"):
            parsed = self._parse_xml_entry(record["raw_xml"])
            record.update(parsed)

        # Extract ArXiv ID from the URL
        arxiv_id = self._extract_arxiv_id(record.get("id", ""))

        # Extract and process authors
        raw_authors = self._extract_authors(record.get("authors", []))

        # Determine the best date to use
        paper_date = self._get_best_date(record)

        # Create Paper instance
        paper = Paper(
            # Core identifiers
            doi=record.get("doi")
            or (self._format_arxiv_doi(arxiv_id) if arxiv_id else None),
            external_source="arxiv",
            # Title and content
            title=record.get("title", "").strip(),
            paper_title=record.get("title", "").strip(),
            abstract=(
                record.get("summary", "").strip() if record.get("summary") else None
            ),
            # Dates
            paper_publish_date=paper_date,
            # Authors (JSON field)
            raw_authors=raw_authors,
            # License and access
            is_open_access=True,  # ArXiv is open access
            oa_status="gold",  # Gold open access for preprints
            # External metadata
            external_metadata={
                "arxiv_id": arxiv_id,
            },
            # Status flags
            retrieved_from_external_source=True,
        )

        # Add URLs from links
        if record.get("links"):
            links = record["links"]
            if "pdf" in links:
                paper.pdf_url = links["pdf"]
            if "alternate" in links:
                paper.url = links["alternate"]
        else:
            # Construct URLs from ArXiv ID if links not provided
            if arxiv_id:
                paper.url = f"http://arxiv.org/abs/{arxiv_id}"  # NOSONAR - Ignore http
                paper.pdf_url = (
                    f"http://arxiv.org/pdf/{arxiv_id}.pdf"  # NOSONAR - Ignore http
                )

        return paper

    def _extract_arxiv_id(self, id_url: str) -> str:
        """
        Extract ArXiv ID from the full URL.

        Args:
            id_url: Full ArXiv URL (e.g., "http://arxiv.org/abs/2509.10432v1")

        Returns:
            ArXiv ID (e.g., "2509.10432v1")
        """
        if not id_url:
            return ""

        # Remove the base URL to get just the ID
        if "/abs/" in id_url:
            return id_url.split("/abs/")[-1]
        elif "/pdf/" in id_url:
            return id_url.split("/pdf/")[-1].replace(".pdf", "")

        # If it's already just an ID, return it
        return id_url

    def _format_arxiv_doi(self, arxiv_id: str) -> str:
        """
        Format ArXiv ID as a DOI.

        ArXiv papers can be cited with DOI format: 10.48550/arXiv.XXXX.XXXXX

        Args:
            arxiv_id: ArXiv ID (e.g., "2509.10432v1")

        Returns:
            DOI formatted string
        """
        if not arxiv_id:
            return ""

        # Remove version number if present
        base_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

        return f"10.48550/arXiv.{base_id}"

    def _get_best_date(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Get the best available date from the record.

        Priority: published > updated

        Args:
            record: ArXiv record

        Returns:
            Date string in YYYY-MM-DD format or None
        """
        date_fields = ["published", "updated"]

        for field in date_fields:
            if record.get(field):
                parsed_date = self._parse_date(record[field])
                if parsed_date:
                    return parsed_date

        return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Parse ISO date string to Paper model format (YYYY-MM-DD).

        Args:
            date_str: ISO format date string (e.g., "2025-09-12T17:38:46Z")

        Returns:
            Date string in YYYY-MM-DD format or None if invalid
        """
        if not date_str:
            return None

        try:
            # Parse ISO format and extract date part
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(f"Invalid date format: {date_str}")
            return None

    def _extract_authors(
        self, authors_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract authors from ArXiv author list.

        Args:
            authors_list: List of author objects from ArXiv

        Returns:
            List of author dictionaries
        """
        if not authors_list:
            return []

        authors = []
        for author_data in authors_list:
            full_name = author_data.get("name", "").strip()
            if not full_name:
                continue

            # Parse name into components
            name_parts = self._parse_author_name(full_name)

            author_dict = {
                "full_name": full_name,
                "first_name": name_parts.get("first_name", ""),
                "last_name": name_parts.get("last_name", ""),
                "middle_name": name_parts.get("middle_name", ""),
                "raw_name": full_name,
            }

            # Add affiliation if available
            if author_data.get("affiliation"):
                author_dict["affiliations"] = [author_data["affiliation"]]

            authors.append(author_dict)

        return authors

    def _parse_author_name(self, full_name: str) -> Dict[str, str]:
        """
        Parse author name into components.

        ArXiv typically provides names in "First Middle Last" format,
        but can also have "Last, First Middle" format.

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

        # Handle space-separated format (First Middle Last)
        parts = full_name.split()

        if not parts:
            return {"first_name": "", "middle_name": "", "last_name": ""}

        if len(parts) == 1:
            return {"first_name": "", "middle_name": "", "last_name": parts[0]}

        if len(parts) == 2:
            return {"first_name": parts[0], "middle_name": "", "last_name": parts[1]}

        # Three or more parts - assume first is first name, last is last name, middle is everything else
        return {
            "first_name": parts[0],
            "middle_name": " ".join(parts[1:-1]),
            "last_name": parts[-1],
        }

    def map_to_authors(self, record: Dict[str, Any]) -> List[Author]:
        """
        Map ArXiv record to author data.

        Note: ArXiv doesn't provide ORCID IDs, so we return empty list
        to avoid creating duplicate authors without proper deduplication.
        """
        # Return empty list - we don't create authors without ORCID IDs
        return []

    def map_to_institutions(self, record: Dict[str, Any]) -> List[Institution]:
        """
        Map ArXiv record to institution data.

        Note: ArXiv doesn't provide ROR IDs for institutions,
        so we return empty list to avoid creating duplicate institutions.
        """
        # Return empty list - we don't create institutions without ROR IDs
        return []

    def map_to_authorships(
        self, paper: Paper, record: Dict[str, Any]
    ) -> List[Authorship]:
        """
        Map ArXiv record to Authorship model instances.

        Note: ArXiv doesn't provide ORCID IDs for authors,
        so we return empty list to avoid creating duplicate authorships.
        """
        # Return empty list - we don't create authorships without proper author IDs
        return []
