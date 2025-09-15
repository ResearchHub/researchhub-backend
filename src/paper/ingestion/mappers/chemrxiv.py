"""
ChemRxiv data mapper for transforming API responses to Paper model format.

Maps ChemRxiv paper records to ResearchHub Paper model fields.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from institution.models import Institution
from paper.models import Paper
from user.related_models.author_institution import AuthorInstitution
from user.related_models.author_model import Author

from .base import BaseMapper

logger = logging.getLogger(__name__)


class ChemRxivMapper(BaseMapper):
    """Maps ChemRxiv paper records to ResearchHub Paper model format."""

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
        version = record.get("version", "1")

        # Extract and process authors
        raw_authors = self._extract_authors(record.get("authors", []))

        # Determine the best date to use
        paper_date = self._get_best_date(record)

        # Extract categories and subjects
        categories = self._extract_categories(record.get("categories", []))
        subject = record.get("subject", {}).get("name", "")

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
            pdf_license=self._extract_license(record.get("license")),
            is_open_access=True,  # ChemRxiv is open access
            oa_status="gold",  # Gold open access for preprints
            # External metadata
            external_metadata={
                "chemrxiv_id": chemrxiv_id,
                "version": version,
                "status": record.get("status"),
                "categories": categories,
                "subject": subject,
                "keywords": record.get("keywords", []),
                "funders": self._extract_funders(record.get("funders", [])),
                "metrics": self._extract_metrics(record.get("metrics", [])),
                "content_type": record.get("contentType", {}).get("name"),
                "submitted_date": record.get("submittedDate"),
                "published_date": record.get("publishedDate"),
                "approved_date": record.get("approvedDate"),
                "status_date": record.get("statusDate"),
                "has_competing_interests": record.get("hasCompetingInterests"),
                "gained_ethics_approval": record.get("gainedEthicsApproval"),
            },
            # Status flags
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

    def _extract_categories(self, categories_list: List[Dict[str, Any]]) -> List[str]:
        """
        Extract category names from ChemRxiv categories.

        Args:
            categories_list: List of category objects

        Returns:
            List of category names
        """
        return [cat.get("name", "") for cat in categories_list if cat.get("name")]

    def _extract_funders(
        self, funders_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract funder information.

        Args:
            funders_list: List of funder objects

        Returns:
            List of funder dictionaries
        """
        funders = []
        for funder in funders_list:
            funder_info = {
                "name": funder.get("name", ""),
                "grant_number": funder.get("grantNumber", ""),
                "funder_id": funder.get("funderId", ""),
            }
            if funder.get("url"):
                funder_info["url"] = funder["url"]
            if funder.get("title"):
                funder_info["title"] = funder["title"]
            funders.append(funder_info)
        return funders

    def _extract_metrics(self, metrics_list: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Extract metrics as a dictionary.

        Args:
            metrics_list: List of metric objects

        Returns:
            Dictionary of metric descriptions to values
        """
        return {
            metric.get("description", ""): metric.get("value", 0)
            for metric in metrics_list
        }

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

    def map_to_author(self, author_data: Dict[str, Any]) -> Author:
        """
        Map author data to ResearchHub Author model instance.

        Args:
            author_data: Author data from ChemRxiv

        Returns:
            Author model instance (not saved to database)
        """
        # Create Author instance with available fields
        author = Author(
            first_name=author_data.get("first_name", ""),
            last_name=author_data.get("last_name", ""),
            orcid_id=author_data.get("orcid_id")
            or author_data.get("orcid"),  # Set ORCID ID
            # Source indicates this came from external ingestion
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        # Store additional data as attributes for optional processing
        author._raw_name = author_data.get("raw_name", "")

        return author

    def get_or_create_institution(
        self, institution_data: Dict[str, Any]
    ) -> Optional[Institution]:
        """
        Get or create an Institution from ChemRxiv institution data.

        Only creates institutions that have a valid ROR ID.
        Since ChemRxiv doesn't provide OpenAlex IDs, we generate a synthetic one
        based on the ROR ID.

        Args:
            institution_data: Institution data from ChemRxiv

        Returns:
            Institution instance or None if no ROR ID or creation fails
        """
        if not institution_data or not institution_data.get("name"):
            return None

        ror_id = institution_data.get("ror_id", "")
        name = institution_data.get("name", "")

        # Only process institutions with ROR IDs
        if not ror_id:
            logger.debug(f"Skipping institution '{name}' - no ROR ID provided")
            return None

        # Try to find existing institution by ROR ID
        try:
            return Institution.objects.get(ror_id=ror_id)
        except Institution.DoesNotExist:
            pass

        # Generate a synthetic OpenAlex ID for ChemRxiv institutions
        # Use ROR ID as base for consistency
        unique_id = ror_id.replace("https://ror.org/", "")
        synthetic_openalex_id = f"chemrxiv_{unique_id}"

        # Check if we already created this synthetic institution
        try:
            return Institution.objects.get(openalex_id=synthetic_openalex_id)
        except Institution.DoesNotExist:
            pass

        # Create new institution with ROR ID
        try:
            institution = Institution.objects.create(
                openalex_id=synthetic_openalex_id,
                ror_id=ror_id,
                display_name=name,
                country_code=institution_data.get("country_code", ""),
                type="education",  # Default type for ChemRxiv institutions
                lineage=[],
                display_name_alternatives=[name],
            )
            logger.info(f"Created institution: {name} with ROR ID: {ror_id}")
            return institution

        except Exception as e:
            logger.error(f"Failed to create institution {name}: {e}")
            return None

    def create_author_institutions(
        self, author: Author, institutions_data: List[Dict[str, Any]]
    ) -> List[AuthorInstitution]:
        """
        Create AuthorInstitution relationships for an author.

        Args:
            author: Author instance
            institutions_data: List of institution data from ChemRxiv

        Returns:
            List of created AuthorInstitution instances
        """
        author_institutions = []

        for inst_data in institutions_data:
            institution = self.get_or_create_institution(inst_data)
            if institution and author.id:
                try:
                    author_inst, created = AuthorInstitution.objects.get_or_create(
                        author=author, institution=institution, defaults={"years": []}
                    )
                    if created:
                        author_institutions.append(author_inst)
                        logger.info(
                            f"Created author-institution relationship: "
                            f"{author.last_name} - {institution.display_name}"
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to create author-institution relationship: {e}"
                    )

        return author_institutions
