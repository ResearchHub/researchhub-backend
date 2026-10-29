"""
OSF registration mapper for transforming OSF API data to ResearchHub models.

Journals built on OSF Registries (e.g. Lifecycle Journal) often leave the
registration's title and description as they were for the research plan, and
put the current manuscript's title and abstract in the submission form answers.
The mapper therefore prefers the form answers over the registration attributes.
"""

import logging
from typing import Any

from hub.mappers.external_category_mapper import ExternalCategoryMapper
from hub.models import Hub
from institution.models import Institution
from paper.ingestion.mappers.base import BaseMapper
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author

logger = logging.getLogger(__name__)


class OSFRegistrationMapper(BaseMapper):
    """Maps OSF registration records to ResearchHub models."""

    def __init__(self, hub_mapper: ExternalCategoryMapper | None = None):
        super().__init__(hub_mapper)

    def validate(self, record: dict[str, Any]) -> bool:
        """
        Validate that the registration is public, not withdrawn, and has a title.
        """
        attributes = record.get("attributes", {})
        if not record.get("id") or not record.get("doi"):
            return False
        if attributes.get("withdrawn"):
            return False
        return bool(self._get_title(record))

    def map_to_paper(self, record: dict[str, Any]) -> Paper:
        """
        Map OSF registration record to Paper model instance.

        Args:
            record: Record from OSFRegistrationClient.fetch_registration,
                with the registration's DOI set under "doi"

        Returns:
            Paper model instance (not saved to database)
        """
        attributes = record.get("attributes", {})
        answers = self._get_answers(record)
        title = self._get_title(record)

        paper = Paper(
            # Core identifiers
            doi=record["doi"].lower(),
            url=record.get("url"),
            external_source=record.get("provider") or "OSF Registries",
            # Title and content
            title=title,
            paper_title=title,
            abstract=answers.get("abstract") or attributes.get("description"),
            # Dates
            paper_publish_date=(attributes.get("date_registered") or "")[:10] or None,
            # Authors (JSON field)
            raw_authors=self._extract_authors(record),
            # Access
            is_open_access=True,  # Only public registrations are returned by OSF
            external_metadata={
                "external_id": record["id"],
                "submission_type": answers.get("submission type"),
            },
            retrieved_from_external_source=True,
        )

        pdf_url = self._extract_pdf_url(answers.get("manuscript file"))
        if pdf_url:
            paper.pdf_url = pdf_url

        return paper

    def _get_answers(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Return form answers keyed by normalized question label,
        e.g. {"short title": "...", "abstract": "..."}.
        """
        responses = record.get("attributes", {}).get("registration_responses") or {}
        labels = record.get("response_labels") or {}

        answers = {}
        for key, value in responses.items():
            label = labels.get(key, "").strip().rstrip(":").strip().lower()
            if label and value not in (None, "", []):
                answers.setdefault(label, value)
        return answers

    def _get_title(self, record: dict[str, Any]) -> str:
        title = self._get_answers(record).get("short title")
        if not isinstance(title, str) or not title.strip():
            title = record.get("attributes", {}).get("title") or ""
        return title.strip()

    def _extract_authors(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract authors, preferring the submission's declared authorship order
        over OSF's contributor list (which may hold non-author collaborators).
        """
        authorship_order = self._get_answers(record).get("authorship order")
        if isinstance(authorship_order, str) and authorship_order.strip():
            names = [
                name.strip() for name in authorship_order.split(",") if name.strip()
            ]
            authors = []
            for name in names:
                first_name, _, last_name = name.rpartition(" ")
                authors.append(
                    {
                        "full_name": name,
                        "first_name": first_name,
                        "last_name": last_name,
                        "raw_name": name,
                    }
                )
            return authors

        return [
            {
                "full_name": contributor.get("full_name", ""),
                "first_name": contributor.get("given_name", ""),
                "last_name": contributor.get("family_name", ""),
                "raw_name": contributor.get("full_name", ""),
            }
            for contributor in record.get("contributors", [])
            if contributor.get("full_name")
        ]

    def _extract_pdf_url(self, files: Any) -> str | None:
        """
        Return the download URL of the first PDF manuscript file, if any.
        Other formats (e.g. .docx) cannot be rendered, so they are skipped.
        """
        if not isinstance(files, list):
            return None
        for file in files:
            if str(file.get("file_name", "")).lower().endswith(".pdf"):
                return file.get("file_urls", {}).get("download")
        return None

    def map_to_authors(self, record: dict[str, Any]) -> list[Author]:
        """
        OSF does not expose contributor ORCIDs, so no Author records are created
        (authors are kept in raw_authors only, to avoid duplicates).
        """
        return []

    def map_to_institutions(self, record: dict[str, Any]) -> list[Institution]:
        return []

    def map_to_authorships(
        self, paper: Paper, record: dict[str, Any]
    ) -> list[Authorship]:
        return []

    def map_to_hubs(self, record: dict[str, Any]) -> list[Hub]:
        return []
