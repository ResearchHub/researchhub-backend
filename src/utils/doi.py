import random
import re
import string
import time
from datetime import datetime
from typing import List, Optional

import requests
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string

from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from researchhub_document.models import ResearchhubPost
from user.models import Author


# Class for handling Digital Object Identifier (DOI) generation and registration with Crossref.
class DOI:
    def __init__(
        self, base_doi: Optional[str] = None, version: Optional[int] = None
    ) -> None:
        self.base_doi = base_doi
        if base_doi is None:
            self.base_doi = self._generate_base_doi()

        self.doi = self.base_doi
        if version is not None:
            self.doi = f"{self.base_doi}.{version}"

    @staticmethod
    def normalize_doi(doi):
        """Convert DOI to standard https://doi.org/ format.
        Handles bare DOIs, doi.org URLs, and full https URLs.
        Returns None if input is invalid.
        """
        if not doi:
            return None

        # Remove any trailing slashes and whitespace
        doi = (
            doi.strip().rstrip("/").lower()
        )  # Convert to lowercase for case-insensitive comparison

        # Handle various URL formats
        if "doi.org" in doi:
            # Extract everything after doi.org/
            parts = doi.split("doi.org/")
            if len(parts) < 2:
                return None
            # Remove any extra 'doi/' in the path
            bare_doi = parts[1].replace("doi/", "")
            return f"https://doi.org/{bare_doi}"

        # If it's a bare DOI (no domain), add the prefix
        return f"https://doi.org/{doi}"

    @staticmethod
    def get_variants(doi):
        """Return all variants of a DOI for searching.
        Args:
            doi: Any DOI format (bare, with domain, or full URL)
        Returns:
            List of variants: [normalized URL, domain-only, bare DOI]
            Empty list if input is invalid
        """
        normalized = DOI.normalize_doi(doi)
        if not normalized:
            return []

        # Extract bare DOI from normalized version
        bare_doi = normalized.split("doi.org/")[-1]

        return [
            normalized,  # Full URL: https://doi.org/XXX
            f"doi.org/{bare_doi}",  # Domain only: doi.org/XXX
            bare_doi,  # Bare DOI: XXX
        ]

    @staticmethod
    def get_bare_doi(doi):
        """Extract bare DOI from any DOI format.
        Args:
            doi: Any DOI format (bare, with domain, or full URL)
        Returns:
            Bare DOI (e.g. "10.1111/ijsw.12716") or None if invalid
        """
        normalized = DOI.normalize_doi(doi)
        if not normalized:
            return None

        # Extract bare DOI from normalized version
        return normalized.split("doi.org/")[-1]

    @staticmethod
    def is_doi(text):
        """
        Checks if a string matches DOI pattern
        """
        if not text or not isinstance(text, str):
            return False

        # Remove common DOI URL prefixes
        cleaned_text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)

        # Simpler DOI pattern that matches 10.XXXX/any.characters
        doi_regex = r"10\.\d{4,}/[-._;()\/:a-zA-Z0-9]+"
        match = re.search(doi_regex, cleaned_text)

        return bool(match)

    # Generate a random DOI using the configured prefix ("10.55277/ResearchHub.") and a random suffix.
    def _generate_base_doi(self) -> str:
        return settings.CROSSREF_DOI_PREFIX + "".join(
            random.choice(string.ascii_lowercase + string.digits)
            for _ in range(settings.CROSSREF_DOI_SUFFIX_LENGTH)
        )

    # Register DOI for a ResearchHub post.
    def register_doi_for_post(
        self, authors: List[Author], title: str, rh_post: ResearchhubPost
    ) -> HttpResponse:
        url = f"{settings.BASE_FRONTEND_URL}/post/{rh_post.id}/{rh_post.slug}"
        return self.register_doi(authors, [], title, url)

    # Register DOI for a ResearchHub paper.
    def register_doi_for_paper(
        self, authors: List[Author], title: str, rh_paper: Paper
    ) -> HttpResponse:
        url = f"{settings.BASE_FRONTEND_URL}/paper/{rh_paper.id}/{rh_paper.slug}"
        return self.register_doi(authors, rh_paper.authorships.all(), title, url)

    def clean_orcid_id(self, orcid_id: str) -> Optional[str]:
        if orcid_id.startswith("https://orcid.org/"):
            orcid_id = orcid_id.replace("https://orcid.org/", "")

        if not re.match(r"^\d{4}-\d{4}-\d{4}-\d{4}$", orcid_id):
            return None
        return orcid_id

    # Main method to register a DOI with Crossref.
    def register_doi(
        self,
        authors: List[Author],
        authorships: List[Authorship],
        title: str,
        url: str,
    ) -> HttpResponse:
        dt = datetime.today()
        contributors = []

        for author in authors:
            author_institution = author.institutions.first()
            authorship = next(
                (a for a in authorships if a.author_id == author.id), None
            )
            institution = None
            if author_institution:
                place = None
                if author_institution.institution.city:
                    place = f"{author_institution.institution.city}, {author_institution.institution.region}"
                institution = {
                    "name": author_institution.institution.display_name,
                    "place": place,
                }

            contributors.append(
                {
                    "first_name": author.first_name,
                    "last_name": author.last_name,
                    "orcid": (
                        self.clean_orcid_id(author.orcid_id)
                        if author.orcid_id
                        else None
                    ),
                    "institution": institution,
                    "department": authorship.department if authorship else None,
                }
            )

        context = {
            "timestamp": int(time.time()),
            "contributors": contributors,
            "title": title,
            "publication_month": dt.month,
            "publication_day": dt.day,
            "publication_year": dt.year,
            "doi": self.doi,
            "url": url,
        }
        crossref_xml = render_to_string("crossref.xml", context)
        files = {
            "operation": (None, "doMDUpload"),
            "login_id": (None, settings.CROSSREF_LOGIN_ID),
            "login_passwd": (None, settings.CROSSREF_LOGIN_PASSWORD),
            "fname": ("crossref.xml", crossref_xml),
        }
        crossref_response = requests.post(settings.CROSSREF_API_URL, files=files)
        return crossref_response
