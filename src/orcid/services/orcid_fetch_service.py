from allauth.socialaccount.models import SocialAccount, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.auth import get_user_model
from django.core.cache import cache

from orcid.identifiers import normalize_orcid
from orcid.services.orcid_email_service import OrcidEmailService
from user.related_models.author_model import Author

User = get_user_model()


class OrcidFetchService:
    """Syncs verified ORCID education emails and author stats."""

    def __init__(self, email_service: OrcidEmailService | None = None) -> None:
        self.email_service = email_service or OrcidEmailService()

    def sync_orcid(self, author_id: int) -> None:
        """Sync an author's ORCID education emails and stats."""
        author, orcid_id = self._get_author_and_orcid_id(author_id)

        self._sync_edu_emails(author.user, orcid_id)
        self._sync_author_stats(author)

    def _get_author_and_orcid_id(self, author_id: int) -> tuple[Author, str]:
        """Get author and ORCID ID, raising if not found or not connected."""
        try:
            author = Author.objects.select_related("user").get(id=author_id)
        except Author.DoesNotExist:
            raise ValueError(f"Author {author_id} not found")

        orcid_id = self._extract_orcid_id(author.orcid_id)
        if not orcid_id:
            raise ValueError(f"Author {author_id} has no ORCID connected")
        return author, orcid_id

    def _sync_edu_emails(self, user: User | None, orcid_id: str) -> None:
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

        verified_edu = self.email_service.fetch_verified_edu_emails(
            orcid_id, token.token
        )

        extra_data = social_account.extra_data or {}
        extra_data["verified_edu_emails"] = verified_edu
        social_account.extra_data = extra_data
        social_account.save(update_fields=["extra_data"])

    def _sync_author_stats(self, author: Author) -> None:
        """Copy h-index and i10-index from merged paper authors to user's author."""
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
            author.save(
                update_fields=["h_index", "i10_index", "two_year_mean_citedness"]
            )
            cache.delete(f"author-{author.id}-summary-stats")

    def _extract_orcid_id(self, orcid_url: str | None) -> str:
        """Extract bare ORCID ID from full URL (e.g., '0000-0001-2345-6789')."""
        _, bare = normalize_orcid(orcid_url)
        return bare or ""
