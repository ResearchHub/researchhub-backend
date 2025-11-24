"""
OpenAlex data mapper for transforming API responses to Paper model format.

Maps OpenAlex work records to ResearchHub Paper model fields.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from hub.models import Hub
from institution.models import Institution
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

from ..base import BaseMapper

logger = logging.getLogger(__name__)

# URL constants
ORCID_ORG_DOMAIN = "orcid.org"
ROR_ORG_DOMAIN = "ror.org"


class OpenAlexMapper(BaseMapper):
    """Maps OpenAlex work records to ResearchHub Paper model format."""

    def __init__(self):
        """
        Constructor.
        """
        super().__init__(hub_mapper=None)

    def validate(self, record: Dict[str, Any]) -> bool:
        """
        Validate an OpenAlex work record has minimum required fields.

        Args:
            record: Work record to validate

        Returns:
            True if valid, False if should be skipped
        """
        # Required fields from OpenAlex API
        required_fields = ["id", "title"]

        for field in required_fields:
            if not record.get(field):
                record_id = record.get("id", "unknown")
                logger.warning(
                    f"Missing required field '{field}' in record {record_id}"
                )
                return False

        # Skip if not a research article
        work_type = record.get("type")
        if work_type not in ["article", "preprint", "posted-content", None]:
            logger.debug(
                f"Skipping non-article type '{work_type}' for record {record['id']}"
            )
            return False

        return True

    def map_to_paper(self, record: Dict[str, Any]) -> Paper:
        """
        Map OpenAlex work record to Paper model instance.

        Args:
            record: OpenAlex work record

        Returns:
            Paper model instance (not saved to database)
        """
        # OpenAlex ID
        openalex_id = self._extract_openalex_id(record.get("id", ""))

        # DOI
        doi = self._extract_doi(record.get("doi"))

        # Authors
        raw_authors = self._extract_authors(record.get("authorships", []))

        # Date
        paper_date = self._get_best_date(record)

        # Open Access
        oa_info = record.get("open_access", {})
        is_oa = oa_info.get("is_oa", False)
        oa_status = oa_info.get("oa_status")

        # Extract license information (includes pdf_url)
        license_info = self._extract_license_info(record)

        # Create Paper instance
        paper = Paper(
            # Core identifiers
            doi=doi,
            openalex_id=openalex_id,
            external_source="openalex",
            # Title and content
            title=record.get("title", "").strip()
            or record.get("display_name", "").strip(),
            paper_title=record.get("title", "").strip()
            or record.get("display_name", "").strip(),
            # Dates
            paper_publish_date=paper_date,
            # Authors (JSON field)
            raw_authors=raw_authors,
            # License and access
            is_open_access=is_oa,
            oa_status=oa_status if is_oa else None,
            pdf_license=license_info.get("license"),
            pdf_license_url=license_info.get("license_url"),
            # Language
            language=record.get("language"),
            # Citations
            citations=record.get("cited_by_count", 0),
            # External metadata
            external_metadata={},
            # URLs
            url=license_info.get("landing_page_url"),
            pdf_url=license_info.get("pdf_url"),
            retrieved_from_external_source=True,
        )

        # Add journal name if available
        if license_info.get("journal_name"):
            paper.external_metadata["journal_name"] = license_info["journal_name"]

        return paper

    def _extract_openalex_id(self, id_url: str) -> str:
        """
        Extract OpenAlex ID from the full URL.

        Args:
            id_url: Full OpenAlex URL (e.g., "https://openalex.org/W2741809807")

        Returns:
            OpenAlex ID (e.g., "W2741809807")
        """
        if not id_url:
            return ""

        # Remove the base URL to get just the ID
        if "openalex.org/" in id_url:
            return id_url.split("openalex.org/")[-1]

        # If it's already just an ID, return it
        return id_url

    def _extract_doi(self, doi_url: Optional[str]) -> Optional[str]:
        """
        Extract DOI from URL format.

        Args:
            doi_url: DOI URL (e.g., "https://doi.org/10.7717/peerj.4375")

        Returns:
            DOI string (e.g., "10.7717/peerj.4375") or None
        """
        if not doi_url:
            return None

        # Remove the URL prefix to get just the DOI
        if "doi.org/" in doi_url:
            return doi_url.split("doi.org/")[-1]

        # If it's already just a DOI, return it
        return doi_url

    def _get_best_date(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Get the best available date from the record.

        Priority: publication_date > publication_year

        Args:
            record: OpenAlex work record

        Returns:
            Date string in YYYY-MM-DD format or None
        """
        # Try publication_date first (YYYY-MM-DD format)
        pub_date = record.get("publication_date")
        if pub_date:
            parsed_date = self._parse_date(pub_date)
            if parsed_date:
                return parsed_date

        # Fall back to publication_year
        pub_year = record.get("publication_year")
        if pub_year:
            return f"{pub_year}-01-01"

        return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Parse date string to Paper model format (YYYY-MM-DD).

        Args:
            date_str: Date string (e.g., "2018-02-13")

        Returns:
            Date string in YYYY-MM-DD format or None if invalid
        """
        if not date_str:
            return None

        try:
            # Parse and validate date
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(f"Invalid date format: {date_str}")
            return None

    def _extract_authors(
        self, authorships_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract authors from OpenAlex authorships list.

        Args:
            authorships_list: List of authorship objects from OpenAlex

        Returns:
            List of author dictionaries
        """
        if not authorships_list:
            return []

        authors = []
        for idx, authorship_data in enumerate(authorships_list):
            author_info = authorship_data.get("author", {})
            display_name = author_info.get("display_name", "").strip()

            if not display_name:
                continue

            # Parse name into components
            raw_author_name = authorship_data.get("raw_author_name", display_name)
            name_parts = self._parse_author_name(raw_author_name)

            author_dict = {
                "full_name": display_name,
                "first_name": name_parts.get("first_name", ""),
                "last_name": name_parts.get("last_name", ""),
                "middle_name": name_parts.get("middle_name", ""),
                "raw_name": raw_author_name,
                "position": idx,
            }

            # Add ORCID if available
            orcid = author_info.get("orcid")
            if orcid:
                # Extract just the ORCID ID without the URL
                if f"{ORCID_ORG_DOMAIN}/" in orcid:
                    orcid = orcid.split(f"{ORCID_ORG_DOMAIN}/")[-1]
                author_dict["orcid"] = orcid

            # Add affiliations if available
            affiliations = []
            for affiliation in authorship_data.get("affiliations", []):
                raw_affiliation = affiliation.get("raw_affiliation_string", "")
                if raw_affiliation:
                    affiliations.append(raw_affiliation)

            if affiliations:
                author_dict["affiliations"] = affiliations

            # Add corresponding author flag
            is_corresponding = authorship_data.get("is_corresponding", False)
            if is_corresponding:
                author_dict["is_corresponding"] = True

            authors.append(author_dict)

        return authors

    def _parse_author_name(self, full_name: str) -> Dict[str, str]:
        """
        Parse author name into components.

        OpenAlex typically provides names in "First Last" or "First Middle Last" format.

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

        # Three or more parts - assume first is first name, last is last name,
        # middle is everything else
        return {
            "first_name": parts[0],
            "middle_name": " ".join(parts[1:-1]),
            "last_name": parts[-1],
        }

    def map_to_authors(self, record: Dict[str, Any]) -> List[Author]:
        """
        Map OpenAlex work record to Author model instances.

        Args:
            record: OpenAlex work record

        Returns:
            List of Author instances (not saved to database).
            Only creates authors with ORCID IDs to enable deduplication.
        """
        authors = []
        authorships_list = record.get("authorships", [])

        for authorship_data in authorships_list:
            author_info = authorship_data.get("author", {})
            orcid = author_info.get("orcid")

            # Only create authors with ORCID IDs for proper deduplication
            if not orcid:
                continue

            # Extract ORCID ID from URL
            if f"{ORCID_ORG_DOMAIN}/" in orcid:
                orcid_id = orcid.split(f"{ORCID_ORG_DOMAIN}/")[-1]
            else:
                orcid_id = orcid

            display_name = author_info.get("display_name", "")
            raw_author_name = authorship_data.get("raw_author_name", display_name)

            # Parse name components
            name_parts = self._parse_author_name(raw_author_name)

            # Extract OpenAlex ID
            openalex_author_id = self._extract_openalex_id(author_info.get("id", ""))

            # Create Author instance
            author = Author(
                first_name=name_parts.get("first_name", ""),
                last_name=name_parts.get("last_name", ""),
                orcid_id=orcid_id,
                openalex_ids=[openalex_author_id] if openalex_author_id else [],
                created_source=Author.SOURCE_OPENALEX,
            )

            authors.append(author)

        return authors

    def map_to_institutions(self, record: Dict[str, Any]) -> List[Institution]:
        """
        Map OpenAlex work record to Institution model instances.

        Args:
            record: OpenAlex work record

        Returns:
            List of Institution instances (not saved to database).
            Only creates institutions with ROR IDs to enable deduplication.
        """
        institutions = []
        seen_oa_ids = set()
        authorships_list = record.get("authorships", [])

        for authorship_data in authorships_list:
            # Extract institutions from authorship
            for institution_info in authorship_data.get("institutions", []):
                ror_url = institution_info.get("ror")

                # Only create institutions with ROR IDs for proper deduplication
                if not ror_url:
                    continue

                # Extract ROR ID from URL
                if f"{ROR_ORG_DOMAIN}/" in ror_url:
                    ror_id = ror_url.split(f"{ROR_ORG_DOMAIN}/")[-1]
                else:
                    ror_id = ror_url

                openalex_id = self._extract_openalex_id(institution_info.get("id", ""))

                # Skip if already processed
                if openalex_id in seen_oa_ids:
                    continue

                seen_oa_ids.add(openalex_id)

                # Create Institution instance
                institution = Institution(
                    display_name=institution_info.get("display_name", ""),
                    ror_id=ror_id,
                    country_code=institution_info.get("country_code"),
                    openalex_id=openalex_id if openalex_id else "",
                    type=institution_info.get("type", ""),
                )

                institutions.append(institution)

        return institutions

    def map_to_authorships(
        self, paper: Paper, record: Dict[str, Any]
    ) -> List[Authorship]:
        """
        Map OpenAlex work record to Authorship model instances.

        Args:
            paper: The Paper instance to create authorships for
            record: OpenAlex work record

        Returns:
            List of Authorship instances (not saved to database).
        """
        authorships = []
        authorships_list = record.get("authorships", [])

        for authorship_data in authorships_list:
            author_info = authorship_data.get("author", {})

            # Extract OpenAlex author ID
            openalex_author_id = self._extract_openalex_id(author_info.get("id", ""))

            # Only create authorships for authors with OpenAlex IDs
            if not openalex_author_id:
                logger.warning(
                    f"Skipping authorship without OpenAlex ID: {author_info}"
                )
                continue

            raw_author_name = authorship_data.get(
                "raw_author_name", author_info.get("display_name", "")
            )

            # Create Authorship instance
            authorship = Authorship(
                paper=paper,
                author_position=authorship_data.get("author_position", ""),
                raw_author_name=raw_author_name,
                is_corresponding=authorship_data.get("is_corresponding", False),
            )

            # Store author OpenAlex ID for later linking
            authorship._author_openalex_id = openalex_author_id

            # Store institution OpenAlex IDs for later linking
            institution_openalex_ids = []
            for institution_info in authorship_data.get("institutions", []):
                openalex_id = self._extract_openalex_id(institution_info.get("id", ""))
                if openalex_id:
                    institution_openalex_ids.append(openalex_id)

            if institution_openalex_ids:
                authorship._institution_openalex_ids = institution_openalex_ids

            authorships.append(authorship)

        return authorships

    def map_to_hubs(self, paper: Paper, record: Dict[str, Any]) -> List[Hub]:
        """
        Map OpenAlex work record to Hub instances.
        """
        hubs = []
        topics = record.get("topics", [])

        for topic in topics:
            hubs.append(
                Hub(
                    name=topic.get("display_name", ""),
                )
            )

        return hubs

    def _extract_license_info(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract license information from OpenAlex record.

        Args:
            record: OpenAlex work record

        Returns:
            Dictionary with 'license', 'license_url', and 'pdf_url' keys
        """
        license_info = {"license": None, "license_url": None, "pdf_url": None}

        # Use primary_location for preprints
        primary_location = record.get("primary_location", {})
        if primary_location:
            license_info["license"] = primary_location.get("license")
            license_info["license_url"] = primary_location.get("license_id")
            license_info["pdf_url"] = primary_location.get("pdf_url")
            license_info["landing_page_url"] = primary_location.get("landing_page_url")
            license_info["journal_name"] = primary_location.get("source", {}).get(
                "display_name"
            )

        return license_info
