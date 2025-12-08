"""
ChemRxiv data mapper for transforming API responses to Paper model format.

Maps ChemRxiv paper records to ResearchHub Paper model fields.
"""

import logging
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


class ChemRxivMapper(BaseMapper):
    """Maps ChemRxiv paper records to ResearchHub Paper model format."""

    _preprint_hub = None

    def __init__(self, hub_mapper: ExternalCategoryMapper):
        """
        Constructor.

        Args:
            hub_mapper: Hub mapper instance.
        """
        super().__init__(hub_mapper)

    @property
    def preprint_hub(self):
        """
        Lazy load the ChemRxiv hub.
        """
        if self._preprint_hub is None:
            self._preprint_hub = Hub.objects.filter(
                slug="chemrxiv", namespace=Hub.Namespace.JOURNAL
            ).first()
        return self._preprint_hub

    def validate(self, record: Dict[str, Any]) -> bool:
        """
        Validate a ChemRxiv paper record has minimum required fields.

        Args:
            record: Paper record to validate

        Returns:
            True if valid, False if should be skipped
        """
        # Required fields from ChemRxiv API
        required_fields = ["id", "doi", "title", "authors"]

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

        # Validate published/submitted date exists
        if not record.get("publishedDate") and not record.get("submittedDate"):
            logger.warning(f"No published or submitted date in record {record['id']}")
            return False

        return True

    def map_to_paper(self, record: Dict[str, Any]) -> Paper:
        """
        Map ChemRxiv record to Paper model instance.

        Args:
            record: ChemRxiv paper record

        Returns:
            Paper model instance (not saved to database)
        """
        # Extract basic fields
        doi = record.get("doi", "")
        chemrxiv_id = record.get("id", "")

        # Extract and process authors
        raw_authors = self._extract_authors(record.get("authors", []))

        # Determine the best date to use
        paper_date = self._get_best_date(record)

        # Extract and parse license
        license_str = self._extract_license(record.get("license"))
        pdf_license = self._parse_license(license_str)

        # Create Paper instance
        paper = Paper(
            # Core identifiers
            doi=doi,
            external_source="chemrxiv",
            # Title and content
            title=record.get("title", ""),
            paper_title=record.get("title", ""),
            abstract=record.get("abstract"),
            # Dates
            paper_publish_date=paper_date,
            # Authors (JSON field)
            raw_authors=raw_authors,
            # License and access
            pdf_license=pdf_license,
            is_open_access=True,  # ChemRxiv is open access
            oa_status="gold",  # Gold open access for preprints
            external_metadata={
                "external_id": chemrxiv_id,
            },
            retrieved_from_external_source=True,
        )

        # Add PDF URL if available
        if record.get("asset"):
            pdf_url = self._extract_pdf_url(record["asset"])
            if pdf_url:
                paper.pdf_url = pdf_url

        # Add HTML URL
        if doi:
            paper.url = (
                f"https://chemrxiv.org/engage/chemrxiv/article-details/{chemrxiv_id}"
            )

        return paper

    def _get_best_date(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Get the best available date from the record.

        Priority: publishedDate > submittedDate > statusDate

        Args:
            record: ChemRxiv record

        Returns:
            Date string in YYYY-MM-DD format or None
        """
        date_fields = ["publishedDate", "submittedDate", "statusDate"]

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
            date_str: ISO format date string (e.g., "2025-09-15T13:35:38.016Z")

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
        Extract authors from ChemRxiv author list.

        Args:
            authors_list: List of author objects from ChemRxiv

        Returns:
            List of author dictionaries
        """
        if not authors_list:
            return []

        authors = []
        for author_data in authors_list:
            first_name = author_data.get("firstName", "")
            last_name = author_data.get("lastName", "")

            # Build full name
            full_name = f"{first_name} {last_name}".strip()
            if not full_name:
                continue

            # Extract institutions with all available metadata
            institutions = []
            for inst in author_data.get("institutions", []):
                inst_name = inst.get("name", "")
                if inst_name:
                    institution_data = {
                        "name": inst_name,
                        "display_name": inst_name,  # Add display_name for compatibility
                        "country": inst.get("country", ""),
                        "country_code": (
                            inst.get("country", "")[:2].upper()
                            if inst.get("country")
                            else ""
                        ),
                        "ror_id": inst.get("rorId", ""),
                    }
                    # Add ROR URL if ROR ID exists
                    if inst.get("rorId"):
                        institution_data["ror"] = inst.get("rorId")
                    institutions.append(institution_data)

            authors.append(
                {
                    "full_name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "title": author_data.get("title", ""),
                    "orcid": author_data.get("orcid", ""),
                    "orcid_id": author_data.get(
                        "orcid", ""
                    ),  # Include orcid_id for compatibility
                    "institutions": institutions,
                    "raw_name": full_name,
                }
            )

        return authors

    def map_to_authors(self, record: Dict[str, Any]) -> List[Author]:
        """
        Map ChemRxiv record to Author model instances.

        Returns list of Author instances with ORCID IDs (not saved to database).
        """
        authors_list = record.get("authors", [])
        if not authors_list:
            return []

        authors = []
        for idx, author_data in enumerate(authors_list):
            orcid_id = author_data.get("orcid", "")

            # Skip authors without ORCID to avoid duplicates
            if not orcid_id:
                continue

            first_name = author_data.get("firstName", "")
            last_name = author_data.get("lastName", "")

            # Create Author instance (not saved)
            author = Author(
                first_name=first_name,
                last_name=last_name,
                orcid_id=orcid_id,
                created_source=Author.SOURCE_RESEARCHHUB,
            )

            # Store additional metadata as private attributes for authorship mapping
            author._raw_name = f"{first_name} {last_name}".strip()
            author._institutions_data = author_data.get("institutions", [])
            author._index = idx
            author._total_authors = len(authors_list)

            authors.append(author)

        return authors

    def map_to_institutions(self, record: Dict[str, Any]) -> List[Institution]:
        """
        Map ChemRxiv record to Institution model instances.

        Returns list of Institution instances with ROR IDs (not saved to database).
        """
        institutions = []
        seen_ror_ids = set()

        # Extract from all authors' institutions
        for author_data in record.get("authors", []):
            for inst in author_data.get("institutions", []):
                ror_id = inst.get("rorId", "")

                # Skip if we've already seen this ROR ID or if no ROR ID
                if not ror_id or ror_id in seen_ror_ids:
                    continue

                seen_ror_ids.add(ror_id)

                # Generate synthetic OpenAlex ID for ChemRxiv institutions
                unique_id = ror_id.replace("https://ror.org/", "")
                synthetic_openalex_id = f"chemrxiv_{unique_id}"

                # Create Institution instance (not saved)
                institution = Institution(
                    openalex_id=synthetic_openalex_id,
                    ror_id=ror_id,
                    display_name=inst.get("name", ""),
                    country_code=(
                        inst.get("country", "")[:2].upper()
                        if inst.get("country")
                        else ""
                    ),
                    type="education",  # Default type
                    lineage=[],
                    associated_institutions=[],
                    display_name_alternatives=[],
                )

                institutions.append(institution)

        return institutions

    def map_to_authorships(
        self, paper: Paper, record: Dict[str, Any]
    ) -> List[Authorship]:
        """
        Map ChemRxiv record to Authorship model instances for a given paper.

        Args:
            paper: The Paper instance to create authorships for
            record: ChemRxiv record containing author data

        Returns:
            List of Authorship instances (not saved to database).
        """
        authorships = []

        # First, get mapped authors and institutions
        authors = self.map_to_authors(record)
        institutions = self.map_to_institutions(record)

        # Create institution lookup by display name
        inst_by_name = {inst.display_name: inst for inst in institutions}

        # Create authorship for each author
        for author in authors:
            # Determine position based on stored metadata
            if hasattr(author, "_index"):
                if author._index == 0:
                    position = "first"
                elif author._index == author._total_authors - 1:
                    position = "last"
                else:
                    position = "middle"
            else:
                position = "middle"  # Default

            # Create Authorship instance (not saved)
            authorship = Authorship(
                paper=paper,
                author=author,
                author_position=position,
                raw_author_name=getattr(author, "_raw_name", ""),
            )

            # Store institutions for later association (after saving)
            authorship._institutions_to_add = []
            if hasattr(author, "_institutions_data"):
                for inst_data in author._institutions_data:
                    inst_name = inst_data.get("name", "")
                    if inst_name in inst_by_name:
                        authorship._institutions_to_add.append(inst_by_name[inst_name])

            authorships.append(authorship)

        return authorships

    def _parse_license(self, license_str: Optional[str]) -> Optional[str]:
        """
        Parse license string to standard format.

        Note: Licenses used by ChemRxiv can be queried via their API:
        https://chemrxiv.org/engage/chemrxiv/public-api/v1/licenses

        Args:
            license_str: License string from ChemRxiv

        Returns:
            Standardized license string or None
        """
        if not license_str:
            return None

        # Currently just return lowercased, hyphenated version
        return license_str.lower().replace(" ", "-").strip()

    def _extract_license(self, license_obj: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Extract license name.

        Args:
            license_obj: License object from ChemRxiv

        Returns:
            License name or None
        """
        if not license_obj:
            return None
        return license_obj.get("name")

    def _extract_pdf_url(self, asset_obj: Dict[str, Any]) -> Optional[str]:
        """
        Extract PDF URL from asset object.

        Args:
            asset_obj: Asset object containing URLs

        Returns:
            PDF URL or None
        """
        if asset_obj and "original" in asset_obj:
            return asset_obj["original"].get("url")
        return None

    def map_to_hubs(self, record: Dict[str, Any]) -> List[Hub]:
        """
        Map ChemRxiv record to Hub (tag) model instances.
        """
        hubs = []

        categories = record.get("categories", None)

        if self._hub_mapper and categories:
            for category in categories:
                category_name = category.get("name")
                if not category_name:
                    continue
                for hub in self._hub_mapper.map(
                    source_category=category_name, source="chemrxiv"
                ):
                    if hub and hub not in hubs:
                        hubs.append(hub)

        if self.preprint_hub and self.preprint_hub not in hubs:
            hubs.append(self.preprint_hub)

        return hubs
