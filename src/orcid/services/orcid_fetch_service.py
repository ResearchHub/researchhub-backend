import logging
from typing import Callable, Optional, Tuple

from allauth.socialaccount.models import SocialAccount, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q

from orcid.clients import OrcidClient
from orcid.services.orcid_email_service import OrcidEmailService
from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author
from utils.openalex import OpenAlex
from purchase.models import Wallet

User = get_user_model()
logger = logging.getLogger(__name__)


def _normalize_orcid(orcid: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Normalize ORCID to (full_url, bare_id) format."""
    if not orcid:
        return None, None
    bare = orcid.replace("https://orcid.org/", "")
    return f"https://orcid.org/{bare}", bare


class OrcidFetchService:
    """Syncs papers and edu emails from ORCID to ResearchHub."""

    def __init__(
        self,
        client: Optional[OrcidClient] = None,
        openalex: Optional[OpenAlex] = None,
        email_service: Optional[OrcidEmailService] = None,
        process_works_fn: Optional[Callable] = None,
    ):
        self.client = client or OrcidClient()
        self.openalex = openalex or OpenAlex()
        self.email_service = email_service or OrcidEmailService(client=self.client)
        self.process_works_fn = process_works_fn or process_openalex_works

    @staticmethod
    def _normalize_orcid(orcid: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Normalize ORCID to (full_url, bare_id) format."""
        if not orcid:
            return None, None
        return f"https://orcid.org/{orcid.replace('https://orcid.org/', '')}", orcid.replace("https://orcid.org/", "")
        
    def sync_orcid(self, author_id: int) -> dict:
        """Sync an author's ORCID papers and edu emails to their ResearchHub profile."""
        author, orcid_id = self._get_author_and_orcid_id(author_id)

        self._sync_edu_emails(author.user, orcid_id)

        dois = self._fetch_dois_from_orcid(orcid_id)
        if not dois:
            return {"papers_processed": 0, "author_id": author_id}

        works = self._fetch_works_from_openalex(dois)
        linked = self._link_papers_to_author(works)
        return {"papers_processed": linked, "author_id": author_id}

    def _get_author_and_orcid_id(self, author_id: int) -> Tuple[Author, str]:
        """Get author and ORCID ID, raising if not found or not connected."""
        try:
            author = Author.objects.select_related("user").get(id=author_id)
        except Author.DoesNotExist:
            raise ValueError(f"Author {author_id} not found")

        orcid_id = self._extract_orcid_id(author.orcid_id)
        if not orcid_id:
            raise ValueError(f"Author {author_id} has no ORCID connected")
        return author, orcid_id

    def _sync_edu_emails(self, user: Optional[User], orcid_id: str) -> None:
        """Sync verified edu emails from ORCID to user's social account."""
        if not user:
            return

        social_account = SocialAccount.objects.filter(
            user=user, provider=OrcidProvider.id
        ).first()
        if not social_account:
            return

        token = SocialToken.objects.filter(account=social_account).first()
        if not token:
            return

        verified_edu = self.email_service.fetch_verified_edu_emails(orcid_id, token.token)

        extra_data = social_account.extra_data or {}
        extra_data["verified_edu_emails"] = verified_edu
        social_account.extra_data = extra_data
        social_account.save(update_fields=["extra_data"])

    def _extract_orcid_id(self, orcid_url: Optional[str]) -> str:
        """Extract bare ORCID ID from full URL (e.g., '0000-0001-2345-6789')."""
        _, bare = _normalize_orcid(orcid_url)
        return bare or ""

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
            sanitized_works = self._sanitize_works(works)
            self.process_works_fn(sanitized_works)
            self._fix_user_author_authorships(sanitized_works)
            return sanitized_works
        return works

    def _sanitize_works(self, works: list[dict]) -> list[dict]:
        """Remove authorships without author IDs to prevent processing errors."""
        sanitized = []
        for work in works:
            work_copy = {**work}
            work_copy["authorships"] = [
                a for a in work.get("authorships", [])
                if a.get("author", {}).get("id") is not None
            ]
            sanitized.append(work_copy)
        return sanitized

    def _fix_user_author_authorships(self, works: list[dict]) -> None:
        """
        Fix authorships incorrectly created with user-connected authors.
        
        Creates paper-specific authors linked via merged_with_author to preserve
        the paper's author name while maintaining the user connection.
        """
        for work in works:
            paper = self._find_paper_by_doi(work.get("doi", ""))
            if not paper:
                continue

            for authorship_data in work.get("authorships", []):
                author_data = authorship_data.get("author", {})
                openalex_author_id = author_data.get("id")
                display_name = author_data.get("display_name", "")

                if not openalex_author_id:
                    continue

                # Find authorship that was created with a user-connected author
                user_authorship = Authorship.objects.filter(
                    paper=paper,
                    author__openalex_ids__contains=[openalex_author_id],
                    author__user__isnull=False,
                ).select_related("author").first()

                if not user_authorship:
                    continue

                user_author = user_authorship.author
                position = authorship_data.get("author_position", "middle")
                is_corresponding = authorship_data.get("is_corresponding") or False

                # Create a new paper-specific author
                name_parts = display_name.split() if display_name else ["Unknown"]
                paper_author = Author.objects.create(
                    first_name=name_parts[0],
                    last_name=name_parts[-1] if len(name_parts) > 1 else "",
                    openalex_ids=[openalex_author_id],
                    merged_with_author=user_author,
                    created_source=Author.SOURCE_OPENALEX,
                )
                Wallet.objects.create(author=paper_author)

                # Remove the OpenAlex ID from the user's author to prevent future conflicts
                if openalex_author_id in user_author.openalex_ids:
                    user_author.openalex_ids.remove(openalex_author_id)
                    user_author.save(update_fields=["openalex_ids"])

                # Update the authorship to use the paper-specific author
                user_authorship.author = paper_author
                user_authorship.raw_author_name = display_name
                user_authorship.author_position = position
                user_authorship.is_corresponding = is_corresponding
                user_authorship.save()

                logger.debug(
                    "Fixed authorship: paper=%d, created author=%d, linked to user=%d",
                    paper.id, paper_author.id, user_author.id,
                )

    def _link_papers_to_author(self, works: list[dict]) -> int:
        """Merge authorships for all authors on papers that have ORCID matches."""
        linked = 0
        linked_author_ids: set[int] = set()

        with transaction.atomic():
            for work in works:
                paper = self._find_paper_by_doi(work.get("doi", ""))
                if not paper:
                    continue

                author_ids = self._merge_authorships_for_paper(paper, work)
                if author_ids:
                    linked += 1
                    linked_author_ids.update(author_ids)

        self._clear_author_caches(linked_author_ids)
        return linked

    def _merge_authorships_for_paper(self, paper: Paper, work: dict) -> set[int]:
        """Merge authorships for all authors on paper that are ORCID-connected in our system."""
        linked_author_ids: set[int] = set()

        for authorship_data in work.get("authorships", []):
            author_data = authorship_data.get("author", {})
            orcid_url = author_data.get("orcid")
            openalex_author_id = author_data.get("id")

            if not orcid_url or not openalex_author_id:
                continue

            # Normalize ORCID to handle both full URL and bare ID formats
            full_orcid, bare_orcid = _normalize_orcid(orcid_url)

            # Find user's author by ORCID (must be OAuth-connected)
            user_author = Author.objects.filter(
                Q(orcid_id=full_orcid) | Q(orcid_id=bare_orcid),
                user__isnull=False,
                user__socialaccount__provider=OrcidProvider.id,
            ).first()

            if not user_author:
                continue

            # Skip if already linked
            if Authorship.objects.filter(paper=paper, author=user_author).exists():
                continue

            # Find the OpenAlex-created authorship by OpenAlex author ID
            openalex_authorship = (
                Authorship.objects.filter(
                    paper=paper, author__openalex_ids__contains=[openalex_author_id]
                )
                .exclude(author=user_author)
                .first()
            )

            if openalex_authorship:
                self._link_authorship_to_user(openalex_authorship, user_author)
                # Track both the user's author and the paper's author for cache clearing
                linked_author_ids.add(user_author.id)
                linked_author_ids.add(openalex_authorship.author_id)

        return linked_author_ids

    def _link_authorship_to_user(
        self, existing: Authorship, user_author: Author
    ) -> None:
        """Link paper's author to user without changing the displayed author name."""
        paper_author = existing.author
        if paper_author.user is None and paper_author.merged_with_author is None:
            paper_author.merged_with_author = user_author
            paper_author.save(update_fields=["merged_with_author"])

    def _clear_author_caches(self, author_ids: set[int]) -> None:
        """Clear publication and summary caches for the given authors."""
        for author_id in author_ids:
            cache.delete(f"author-{author_id}-publications")
            cache.delete(f"author-{author_id}-summary-stats")

    def _find_paper_by_doi(self, raw_doi: str) -> Optional[Paper]:
        """Find paper by DOI (handles both full URL and bare DOI formats)."""
        if not raw_doi:
            return None
        clean_doi = raw_doi.replace("https://doi.org/", "")
        return Paper.objects.filter(
            Q(doi__iexact=raw_doi) | Q(doi__iexact=clean_doi)
        ).first()
