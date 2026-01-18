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
from purchase.models import Wallet
from utils.openalex import OpenAlex

User = get_user_model()
logger = logging.getLogger(__name__)


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
        bare = orcid.replace("https://orcid.org/", "")
        return f"https://orcid.org/{bare}", bare

    def sync_orcid(self, author_id: int) -> dict:
        """Sync an author's ORCID papers and edu emails to their ResearchHub profile."""
        author, orcid_id = self._get_author_and_orcid_id(author_id)

        self._sync_edu_emails(author.user, orcid_id)

        dois = self._fetch_dois_from_orcid(orcid_id)
        if not dois:
            return {"papers_processed": 0, "author_id": author_id}

        works = self._fetch_works_from_openalex(dois)
        linked = self._link_papers_to_author(works, syncing_author=author)
        self._sync_author_stats(author)
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

    def _sync_author_stats(self, author: Author) -> None:
        """Copy h-index and i10-index from merged paper authors to user's author."""
        # Find the best stats from any paper author merged with this user
        merged_author = (
            Author.objects.filter(merged_with_author=author)
            .exclude(h_index=0, i10_index=0)
            .order_by("-h_index")
            .first()
        )
        if merged_author:
            author.h_index = merged_author.h_index
            author.i10_index = merged_author.i10_index
            author.two_year_mean_citedness = merged_author.two_year_mean_citedness
            author.save(update_fields=["h_index", "i10_index", "two_year_mean_citedness"])

    def _extract_orcid_id(self, orcid_url: Optional[str]) -> str:
        """Extract bare ORCID ID from full URL (e.g., '0000-0001-2345-6789')."""
        _, bare = self._normalize_orcid(orcid_url)
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
        return [
            {**w, "authorships": [a for a in w.get("authorships", []) if a.get("author", {}).get("id")]}
            for w in works
        ]

    def _fix_user_author_authorships(self, works: list[dict]) -> None:
        """
        Fix authorships incorrectly created with user-connected authors.
        
        Creates paper-specific authors linked via merged_with_author to preserve
        the paper's author name while maintaining the user connection.
        """
        with transaction.atomic():
            for work in works:
                paper = self._find_paper_by_doi(work.get("doi", ""))
                if not paper:
                    continue

                for openalex_authorship in work.get("authorships", []):
                    openalex_author = openalex_authorship.get("author", {})
                    openalex_author_id = openalex_author.get("id")
                    display_name = openalex_author.get("display_name", "")

                    # Find authorship created with a user-connected author
                    user_authorship = Authorship.objects.filter(
                        paper=paper,
                        author__openalex_ids__contains=[openalex_author_id],
                        author__user__isnull=False,
                    ).select_related("author").first()

                    if not user_authorship:
                        continue

                    user_author = user_authorship.author

                    # Reuse existing paper-specific author or create new one
                    paper_author = Author.objects.filter(
                        openalex_ids__contains=[openalex_author_id],
                        user__isnull=True,
                    ).first()

                    if not paper_author:
                        name_parts = display_name.split() if display_name and display_name.strip() else ["Unknown"]
                        paper_author = Author.objects.create(
                            first_name=name_parts[0],
                            last_name=name_parts[-1] if len(name_parts) > 1 else "",
                            openalex_ids=[openalex_author_id],
                            merged_with_author=user_author,
                            created_source=Author.SOURCE_OPENALEX,
                        )
                        Wallet.objects.create(author=paper_author)
                    elif not paper_author.merged_with_author:
                        paper_author.merged_with_author = user_author
                        paper_author.save(update_fields=["merged_with_author"])

                    # Update authorship to use paper-specific author
                    user_authorship.author = paper_author
                    user_authorship.raw_author_name = display_name
                    user_authorship.author_position = openalex_authorship.get("author_position", "middle")
                    user_authorship.is_corresponding = openalex_authorship.get("is_corresponding") or False
                    user_authorship.save()

                    logger.debug(
                        "Fixed authorship: paper=%d, author=%d, user=%d",
                        paper.id, paper_author.id, user_author.id,
                    )

    def _link_papers_to_author(
        self, works: list[dict], syncing_author: Optional[Author] = None
    ) -> int:
        """Merge authorships for all authors on papers that have ORCID matches."""
        linked = 0
        linked_author_ids: set[int] = set()

        # Validate syncing author has OAuth once (not per-paper)
        if syncing_author and not self._has_orcid_oauth(syncing_author):
            syncing_author = None

        with transaction.atomic():
            for work in works:
                paper = self._find_paper_by_doi(work.get("doi", ""))
                if not paper:
                    continue

                # First, link the syncing user's authorship (we know they wrote this paper)
                syncing_linked = False
                if syncing_author:
                    paper_author_id = self._link_work_to_author(
                        paper, work, syncing_author
                    )
                    if paper_author_id:
                        syncing_linked = True
                        linked_author_ids.add(syncing_author.id)
                        linked_author_ids.add(paper_author_id)

                # Then, link any other ORCID-connected authors on this paper
                author_ids = self._merge_authorships_for_paper(paper, work)
                if author_ids:
                    linked_author_ids.update(author_ids)

                if syncing_linked or author_ids:
                    linked += 1

        self._clear_author_caches(linked_author_ids)
        return linked

    def _has_orcid_oauth(self, author: Author) -> bool:
        """Check if author has ORCID OAuth connected (not just orcid_id set)."""
        if not author.user:
            return False
        return SocialAccount.objects.filter(
            user=author.user, provider=OrcidProvider.id
        ).exists()

    def _link_work_to_author(
        self, paper: Paper, work: dict, author: Author
    ) -> Optional[int]:
        """
        Link the user's authorship on this paper.
        
        Returns the paper author's id if linked, None otherwise.
        """
        orcid_id = self._extract_orcid_id(author.orcid_id)
        author_openalex_ids = set(author.openalex_ids or [])

        # Find the user's OpenAlex author ID on this paper
        openalex_author_id = self._find_author_openalex_id(
            work, orcid_id, author_openalex_ids
        )
        if not openalex_author_id:
            return None

        # Find the paper's authorship with this OpenAlex author ID
        authorship = (
            Authorship.objects.filter(
                paper=paper, author__openalex_ids__contains=[openalex_author_id]
            )
            .exclude(author=author)
            .select_related("author")
            .first()
        )

        if not authorship:
            return None

        if self._link_authorship_to_user(authorship, author):
            return authorship.author_id
        return None

    def _find_author_openalex_id(
        self, work: dict, orcid: str, openalex_ids: set[str]
    ) -> Optional[str]:
        """Find the OpenAlex author ID matching ORCID or known IDs."""
        for openalex_authorship in work.get("authorships", []):
            openalex_author = openalex_authorship.get("author", {})
            author_id = openalex_author.get("id")
            orcid_url = openalex_author.get("orcid") or ""

            # Match by ORCID first (most reliable)
            if orcid and orcid in orcid_url:
                return author_id

            # Fallback: match by known OpenAlex IDs
            if author_id and author_id in openalex_ids:
                return author_id

        return None

    def _merge_authorships_for_paper(self, paper: Paper, work: dict) -> set[int]:
        """Merge authorships for all authors on paper that are ORCID-connected in our system."""
        linked_author_ids: set[int] = set()

        for openalex_authorship in work.get("authorships", []):
            openalex_author = openalex_authorship.get("author", {})
            orcid_url = openalex_author.get("orcid")
            openalex_author_id = openalex_author.get("id")

            if not orcid_url or not openalex_author_id:
                continue

            # Normalize ORCID to handle both full URL and bare ID formats
            full_orcid, bare_orcid = self._normalize_orcid(orcid_url)

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
            paper_authorship = (
                Authorship.objects.filter(
                    paper=paper, author__openalex_ids__contains=[openalex_author_id]
                )
                .exclude(author=user_author)
                .first()
            )

            if paper_authorship:
                if self._link_authorship_to_user(paper_authorship, user_author):
                    linked_author_ids.add(user_author.id)
                    linked_author_ids.add(paper_authorship.author_id)

        return linked_author_ids

    def _link_authorship_to_user(
        self, authorship: Authorship, user_author: Author
    ) -> bool:
        """Link paper's author to user without changing the displayed author name."""
        paper_author = authorship.author
        if paper_author.user is None and paper_author.merged_with_author is None:
            paper_author.merged_with_author = user_author
            paper_author.save(update_fields=["merged_with_author"])
            return True
        return False

    def _clear_author_caches(self, author_ids: set[int]) -> None:
        """Clear profile caches for the given authors."""
        for author_id in author_ids:
            cache.delete(f"author-{author_id}-profile")
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
