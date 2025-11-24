"""
ArXiv OAI data mapper for transforming OAI responses to Paper model format.
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional

from hub.mappers.external_category_mapper import ExternalCategoryMapper
from hub.models import Hub
from institution.models import Institution
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

from ..base import BaseMapper

logger = logging.getLogger(__name__)


class ArXivOAIMapper(BaseMapper):
    """
    Maps ArXiv OAI paper records to ResearchHub Paper model format.
    """

    # XML namespaces
    OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"
    ARXIV_NS = "{http://arxiv.org/OAI/arXiv/}"
    ARXIV_RAW_NS = "{http://arxiv.org/OAI/arXivRaw/}"
    DC_NS = "{http://purl.org/dc/elements/1.1/}"

    _preprint_hub = None

    def __init__(self, hub_mapper: ExternalCategoryMapper):
        """
        Constructor.

        Args:
            hub_mapper: Hub mapper instance.
        """
        super().__init__(hub_mapper)

    @property
    def preprint_hub(self) -> Optional[Hub]:
        """
        Lazy load the ArXiv hub.
        """
        if self._preprint_hub is None:
            self._preprint_hub = Hub.objects.filter(
                slug="arxiv", namespace=Hub.Namespace.JOURNAL
            ).first()
        return self._preprint_hub

    def _parse_xml_metadata(self, raw_xml: str) -> Dict[str, Any]:
        """
        Parse raw OAI metadata XML into a dictionary.

        Args:
            raw_xml: Raw XML string for metadata section

        Returns:
            Dictionary with parsed fields
        """
        try:
            root = ET.fromstring(raw_xml)

            # The formats are possible: arXiv, arXivRaw, oai_dc (Dublin Core)
            # The following tries to parse for these formats in order.

            # Find `arXiv` metadata (standard format)
            arxiv_elem = root.find(f".//{self.ARXIV_NS}arXiv")

            if arxiv_elem is None:
                # Try `arXivRaw` format
                arxiv_elem = root.find(f".//{self.ARXIV_RAW_NS}arXivRaw")

            if arxiv_elem is None:
                # Try `oai_dc` format
                return self._parse_dublin_core(root)

            # Determine which namespace to use
            ns = (
                self.ARXIV_NS
                if arxiv_elem.tag.startswith(self.ARXIV_NS)
                else self.ARXIV_RAW_NS
            )

            # Extract basic fields
            entry_data: Dict[str, Any] = {
                "id": self._get_text(arxiv_elem, f"{ns}id"),
                "title": self._get_text(arxiv_elem, f"{ns}title"),
                "abstract": self._get_text(arxiv_elem, f"{ns}abstract"),
                "created": self._get_text(arxiv_elem, f"{ns}created"),
                "updated": self._get_text(arxiv_elem, f"{ns}updated"),
            }

            # Extract authors
            authors: List[Dict[str, str]] = []
            authors_elem = arxiv_elem.find(f"{ns}authors")
            if authors_elem is not None:
                for author_elem in authors_elem.findall(f"{ns}author"):
                    keyname = self._get_text(author_elem, f"{ns}keyname")
                    forenames = self._get_text(author_elem, f"{ns}forenames")
                    suffix = self._get_text(author_elem, f"{ns}suffix")

                    author_data = {}
                    if forenames and keyname:
                        full_name = f"{forenames} {keyname}"
                        if suffix:
                            full_name += f" {suffix}"
                        author_data["name"] = full_name
                        author_data["keyname"] = keyname
                        author_data["forenames"] = forenames
                        if suffix:
                            author_data["suffix"] = suffix
                    elif keyname:
                        author_data["name"] = keyname
                        author_data["keyname"] = keyname

                    # Check for affiliation
                    affiliation = self._get_text(author_elem, f"{ns}affiliation")
                    if affiliation:
                        author_data["affiliation"] = affiliation

                    if author_data:
                        authors.append(author_data)

            entry_data["authors"] = authors

            # Extract categories
            categories_text = self._get_text(arxiv_elem, f"{ns}categories")
            if categories_text:
                # Categories are space-separated
                entry_data["categories"] = categories_text.split()
                # First category is primary
                if entry_data["categories"]:
                    entry_data["primary_category"] = entry_data["categories"][0]

            # Extract optional fields
            entry_data["comments"] = self._get_text(arxiv_elem, f"{ns}comments")
            entry_data["journal_ref"] = self._get_text(arxiv_elem, f"{ns}journal-ref")
            entry_data["doi"] = self._get_text(arxiv_elem, f"{ns}doi")
            entry_data["license"] = self._get_text(arxiv_elem, f"{ns}license")

            # Construct URLs from ArXiv ID
            if entry_data.get("id"):
                arxiv_id = entry_data["id"]
                entry_data["links"] = {
                    "alternate": f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                }

            return entry_data

        except ET.ParseError as e:
            logger.error(f"Failed to parse OAI metadata XML: {e}")
            return {}

    def _parse_dublin_core(self, root: ET.Element) -> Dict[str, Any]:
        """
        Parse Dublin Core metadata format as fallback.

        Args:
            root: Root XML element

        Returns:
            Dictionary with parsed fields
        """
        dc_elem = root.find(f".//{self.DC_NS}dc")
        if dc_elem is None:
            return {}

        entry_data = {
            "title": self._get_text(dc_elem, f"{self.DC_NS}title"),
            "abstract": self._get_text(dc_elem, f"{self.DC_NS}description"),
            "created": self._get_text(dc_elem, f"{self.DC_NS}date"),
        }

        # Extract authors from creator fields
        authors = []
        for creator_elem in dc_elem.findall(f"{self.DC_NS}creator"):
            if creator_elem.text:
                authors.append({"name": creator_elem.text.strip()})
        entry_data["authors"] = authors

        # Extract identifier (may contain arXiv ID)
        identifier = self._get_text(dc_elem, f"{self.DC_NS}identifier")
        if identifier and "arxiv.org" in identifier.lower():
            # Extract ID from URL
            if "/abs/" in identifier:
                entry_data["id"] = identifier.split("/abs/")[-1]
            elif ":" in identifier:
                entry_data["id"] = identifier.split(":")[-1]

        return entry_data

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
        Validate an ArXiv OAI paper record has minimum required fields.

        Args:
            record: Paper record to validate (may contain raw_xml)

        Returns:
            True if valid, False if should be skipped
        """
        # If record contains raw_xml, parse it first
        if "raw_xml" in record and not record.get("id"):
            parsed = self._parse_xml_metadata(record["raw_xml"])
            record.update(parsed)

        # Required fields from ArXiv OAI
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

        # Validate created or updated date exists
        if not record.get("created") and not record.get("updated"):
            logger.warning(f"No created or updated date in record {record['id']}")
            return False

        return True

    def map_to_paper(self, record: Dict[str, Any]) -> Paper:
        """
        Map ArXiv OAI record to Paper model instance.

        Args:
            record: ArXiv OAI paper record (may contain raw_xml)

        Returns:
            Paper model instance (not saved to database)
        """
        # If record contains raw_xml, parse it first
        if "raw_xml" in record and not record.get("id"):
            parsed = self._parse_xml_metadata(record["raw_xml"])
            record.update(parsed)

        # Extract ArXiv ID (already in clean format from OAI)
        arxiv_id = record.get("id", "")

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
                record.get("abstract", "").strip() if record.get("abstract") else None
            ),
            # Dates
            paper_publish_date=paper_date,
            # Authors (JSON field)
            raw_authors=raw_authors,
            # License and access
            is_open_access=True,  # ArXiv is open access
            oa_status="gold",  # Gold open access for preprints
            pdf_license=self._parse_license(record.get("license")),
            pdf_license_url=record.get("license"),
            # External metadata
            external_metadata={
                "external_id": arxiv_id,
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
                paper.url = f"https://arxiv.org/abs/{arxiv_id}"
                paper.pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        return paper

    def _format_arxiv_doi(self, arxiv_id: str) -> str:
        """
        Format ArXiv ID as a DOI.

        ArXiv papers can be cited with DOI format: 10.48550/arXiv.XXXX.XXXXX

        Args:
            arxiv_id: ArXiv ID (e.g., "2507.00004")

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

        Priority: created > updated

        Args:
            record: ArXiv OAI record

        Returns:
            Date string in YYYY-MM-DD format or None
        """
        date_fields = ["created", "updated"]

        for field in date_fields:
            if record.get(field):
                parsed_date = self._parse_date(record[field])
                if parsed_date:
                    return parsed_date

        return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Parse date string to Paper model format (YYYY-MM-DD).

        Args:
            date_str: Date string (e.g., "2025-07-10" or "2025-07-10T12:00:00Z")

        Returns:
            Date string in YYYY-MM-DD format or None if invalid
        """
        if not date_str:
            return None

        try:
            # Handle ISO format with time
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d")
            # Handle simple date format (YYYY-MM-DD)
            elif len(date_str) >= 10:
                # Validate it's a valid date
                datetime.strptime(date_str[:10], "%Y-%m-%d")
                return date_str[:10]
            else:
                return None
        except (ValueError, TypeError):
            logger.warning(f"Invalid date format: {date_str}")
            return None

    def _parse_license(self, license_str: Optional[str]) -> Optional[str]:
        """
        Parse license string to standard format.

        Converts Creative Commons and other license URLs to standardized
        short format.
        Example:
        http://creativecommons.org/licenses/by-nc-nd/4.0/ -> cc-by-nc-nd-4.0

        Args:
            license_str: License URL or short format string

        Returns:
            Standardized license string or None
        """
        if not license_str:
            return None

        license_lower = license_str.lower().strip()
        if not license_lower:
            return None

        # Handle Creative Commons URLs
        # Example: http://creativecommons.org/licenses/by-nc-nd/4.0/
        cc_match = re.search(
            r"creativecommons\.org/licenses/([^/]+)/([^/]+)", license_lower
        )
        if cc_match:
            license_type, version = cc_match.groups()
            return f"cc-{license_type}-{version}"

        # Handle arXiv-specific licenses
        if "arxiv.org" in license_lower and "nonexclusive" in license_lower:
            return "arxiv-nonexclusive-distrib-1.0"

        # Handle public domain
        if "publicdomain" in license_lower or "cc0" in license_lower:
            return "cc0-1.0"

        # Return the original string if no pattern matches
        return license_lower.replace("_", "-").strip()

    def _extract_authors(
        self, authors_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract authors from ArXiv OAI author list.

        Args:
            authors_list: List of author objects from ArXiv OAI

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
            # OAI provides keyname and forenames separately
            if "keyname" in author_data and "forenames" in author_data:
                name_parts = {
                    "first_name": author_data.get("forenames", ""),
                    "last_name": author_data.get("keyname", ""),
                    "middle_name": "",
                }
            else:
                # Fall back to parsing full name
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

        Args:
            full_name: Full author name

        Returns:
            Dictionary with first_name, middle_name, last_name
        """
        # Handle space-separated format (First Middle Last)
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

    def map_to_authors(self, record: Dict[str, Any]) -> List[Author]:
        """
        Map ArXiv OAI record to author data.

        Note: ArXiv doesn't provide ORCID IDs, so we return empty list
        to avoid creating duplicate authors without proper deduplication.
        """
        # Return empty list - we don't create authors without ORCID IDs
        return []

    def map_to_institutions(self, record: Dict[str, Any]) -> List[Institution]:
        """
        Map ArXiv OAI record to institution data.

        Note: ArXiv doesn't provide ROR IDs for institutions,
        so we return empty list to avoid creating duplicate institutions.
        """
        # Return empty list - we don't create institutions without ROR IDs
        return []

    def map_to_authorships(
        self, paper: Paper, record: Dict[str, Any]
    ) -> List[Authorship]:
        """
        Map ArXiv OAI record to Authorship model instances.

        Note: ArXiv doesn't provide ORCID IDs for authors,
        so we return empty list to avoid creating duplicate authorships.
        """
        # Return empty list - we don't create authorships without proper IDs
        return []

    def map_to_hubs(self, paper: Paper, record: Dict[str, Any]) -> List[Hub]:
        """
        Map arXiv OAI record to Hub (tag) model instances.
        """
        hubs = []
        primary_category = record.get("primary_category")

        if self._hub_mapper and primary_category:
            for hub in self._hub_mapper.map(primary_category, "arxiv"):
                if hub and hub not in hubs:
                    hubs.append(hub)

        if self.preprint_hub and self.preprint_hub not in hubs:
            hubs.append(self.preprint_hub)

        return hubs
