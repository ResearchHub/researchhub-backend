from functools import lru_cache

from django.contrib.contenttypes.models import ContentType
from django.db.models import QuerySet

from discussion.constants.flag_reasons import NOT_SPECIFIED
from discussion.models import Flag
from user.models import Author, User, Verdict


@lru_cache(maxsize=1)
def _get_author_content_type() -> ContentType:
    """Cached lookup for Author content type."""
    return ContentType.objects.get_for_model(Author)


def _get_verdict_choice(reason_choice: str) -> str:
    """Convert a flag reason to its NOT_ verdict equivalent."""
    return f"NOT_{reason_choice}" if reason_choice else NOT_SPECIFIED


class UserFlagService:
    """Service for managing user/author flags."""

    @staticmethod
    def get_open_flags(author: Author) -> QuerySet[Flag]:
        """Get all unresolved flags for an author."""
        return (
            Flag.objects.filter(
                content_type=_get_author_content_type(),
                object_id=author.id,
                verdict__isnull=True,
            )
            .select_related("created_by")
            .order_by("-created_date")
        )

    @staticmethod
    def create_flag(
        author: Author,
        created_by: User,
        reason: str,
        reason_memo: str = "",
    ) -> Flag:
        """Create or re-open a flag on an author."""
        content_type = _get_author_content_type()

        existing_flag = Flag.objects.filter(
            content_type=content_type,
            object_id=author.id,
            created_by=created_by,
        ).first()

        if existing_flag:
            # Delete verdict if exists (re-open the flag)
            if hasattr(existing_flag, "verdict"):
                existing_flag.verdict.delete()

            # Update flag with new reason info
            existing_flag.reason = reason
            existing_flag.reason_choice = reason
            existing_flag.reason_memo = reason_memo
            existing_flag.save()
            return existing_flag

        return Flag.objects.create(
            content_type=content_type,
            object_id=author.id,
            created_by=created_by,
            reason=reason,
            reason_choice=reason,
            reason_memo=reason_memo,
        )

    @staticmethod
    def resolve_flags(author: Author, resolved_by: User) -> int:
        """Resolve all open flags for an author. Returns count resolved."""
        open_flags = list(UserFlagService.get_open_flags(author))
        if not open_flags:
            return 0

        verdicts = [
            Verdict(
                created_by=resolved_by,
                flag=flag,
                verdict_choice=_get_verdict_choice(flag.reason_choice),
                is_content_removed=False,
            )
            for flag in open_flags
        ]
        Verdict.objects.bulk_create(verdicts)
        return len(verdicts)
