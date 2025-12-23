import logging
from typing import Callable, Optional, Tuple

from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.db import transaction
from django.db.models import Q

from orcid.clients import OrcidClient
from orcid.config import ORCID_BASE_URL
from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author
from utils.openalex import OpenAlex

logger = logging.getLogger(__name__)


class OrcidFetchService:
    """Syncs papers from ORCID to ResearchHub by matching DOIs via OpenAlex."""

    def __init__(
        self,
        client: Optional[OrcidClient] = None,
        openalex: Optional[OpenAlex] = None,
        process_works_fn: Optional[Callable] = None,
    ):
        self.client = client or OrcidClient()
        self.openalex = openalex or OpenAlex()
        self.process_works_fn = process_works_fn or process_openalex_works

    def sync_papers(self, author_id: int) -> dict:
        """Sync an author's ORCID papers to their ResearchHub profile."""
        author, orcid_id = self._get_validated_author(author_id)
        dois = self._fetch_dois_from_orcid(orcid_id)

        if not dois:
            return {"papers_processed": 0, "author_id": author_id}

        works = self._fetch_works_from_openalex(dois)
        linked = self._link_papers_to_author(author, works, orcid_id)
        return {"papers_processed": linked, "author_id": author_id}

    def _get_validated_author(self, author_id: int) -> Tuple[Author, str]:
        """Get author and extract ORCID ID, raising if not connected."""
        try:
            author = Author.objects.get(id=author_id)
        except Author.DoesNotExist:
            raise ValueError(f"Author {author_id} not found")

        orcid_id = self._extract_orcid_id(author.orcid_id)
        if not orcid_id:
            raise ValueError(f"Author {author_id} has no ORCID connected")
        return author, orcid_id

    def _extract_orcid_id(self, orcid_url: Optional[str]) -> str:
        """Extract bare ORCID ID from full URL (e.g., '0000-0001-2345-6789')."""
        if not orcid_url:
            return ""
        return orcid_url.replace(f"{ORCID_BASE_URL}/", "").strip("/")

    def _fetch_dois_from_orcid(self, orcid_id: str) -> list[str]:
        """Fetch DOIs from user's ORCID works."""
        works_data = self.client.get_works(orcid_id)
        return self._extract_dois(works_data)

    def _extract_dois(self, works_data: dict) -> list[str]:
        """Extract DOIs from ORCID works response."""
        dois = []
        for group in works_data.get("group", []):
            for summary in group.get("work-summary", []):
                for ext_id in summary.get("external-ids", {}).get("external-id", []):
                    if ext_id.get("external-id-type") == "doi":
                        if doi := ext_id.get("external-id-value"):
                            dois.append(doi)
                        break
        return dois

    def _fetch_works_from_openalex(self, dois: list[str]) -> list[dict]:
        """Fetch works from OpenAlex and process them into ResearchHub."""
        works = [w for doi in dois if (w := self.openalex.get_work_by_doi(doi))]
        if works:
            self.process_works_fn(works)
        return works

    def _link_papers_to_author(
        self, author: Author, works: list[dict], orcid_id: str
    ) -> int:
        """Merge authorships for all authors on papers that have ORCID matches."""
        linked = 0
        with transaction.atomic():
            for work in works:
                paper = self._find_paper_by_doi(work.get("doi", ""))
                if not paper:
                    continue

                # Merge ALL authorships on this paper that have ORCID matches
                merged_count = self._merge_authorships_for_paper(paper, work)
                if merged_count > 0:
                    linked += 1
        return linked

    def _merge_authorships_for_paper(self, paper: Paper, work: dict) -> int:
        """Merge authorships for all authors on paper that are ORCID-connected in our system."""
        merged = 0

        for authorship_data in work.get("authorships", []):
            orcid_url = authorship_data.get("author", {}).get("orcid")
            if not orcid_url:
                continue

            # Find an Author with this ORCID who is actually connected to ORCID
            user_author = Author.objects.filter(
                orcid_id=orcid_url,
                user__isnull=False,
                user__socialaccount__provider=OrcidProvider.id,
            ).first()

            if not user_author:
                continue

            # Skip if already linked
            if Authorship.objects.filter(paper=paper, author=user_author).exists():
                continue

            # Find the OpenAlex authorship to merge
            openalex_authorship = (
                Authorship.objects.filter(paper=paper, author__orcid_id=orcid_url)
                .exclude(author=user_author)
                .first()
            )

            if openalex_authorship:
                position = authorship_data.get(
                    "author_position", Authorship.MIDDLE_AUTHOR_POSITION
                )
                self._transfer_authorship(openalex_authorship, user_author, position)
                merged += 1

        return merged

    def _transfer_authorship(
        self, existing: Authorship, user_author: Author, position: str
    ) -> None:
        """Transfer authorship from OpenAlex author to user's author."""
        old_author = existing.author
        existing.author = user_author
        existing.author_position = position
        existing.save(update_fields=["author", "author_position"])

        if old_author.user is None and old_author.merged_with_author is None:
            old_author.merged_with_author = user_author
            old_author.save(update_fields=["merged_with_author"])

    def _find_paper_by_doi(self, raw_doi: str) -> Optional[Paper]:
        """Find paper by DOI (handles both full URL and bare DOI formats)."""
        if not raw_doi:
            return None
        clean_doi = raw_doi.replace("https://doi.org/", "")
        return Paper.objects.filter(
            Q(doi__iexact=raw_doi) | Q(doi__iexact=clean_doi)
        ).first()
