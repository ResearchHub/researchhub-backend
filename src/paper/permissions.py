from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from paper.models import Paper
from paper.related_models.paper_version import PaperVersion
from user.models import Author
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


def is_legacy_journal_paper(paper_id: int | str | None) -> bool:
    """Return whether a paper ID belongs to the retired ResearchHub Journal."""
    if paper_id is None or not str(paper_id).isdecimal():
        return False

    return PaperVersion.objects.filter(
        paper_id=paper_id,
        journal=PaperVersion.RESEARCHHUB,
    ).exists()


class UpdatePaper(RuleBasedPermission):
    message = "Not enough reputation to update paper."

    def satisfies_rule(self, request: Request) -> bool:
        """Return whether the requester may update a paper."""
        return request.user.reputation >= 1 and not request.user.is_suspended


class CanEditLegacyJournalPaper(BasePermission):
    """Allow interactions with legacy papers while preventing content changes."""

    message = "Legacy journal paper content is read-only."

    def has_object_permission(
        self,
        request: Request,
        view: APIView,
        obj: Paper,
    ) -> bool:
        """Allow reads and vote removal but reject legacy paper changes."""
        return (
            request.method in SAFE_METHODS
            or getattr(view, "action", None) == "delete_user_vote"
            or not is_legacy_journal_paper(obj.id)
        )


class IsAuthor(AuthorizationBasedPermission):
    message = "User is not authorized."

    def is_authorized(self, request, view, obj):
        author = Author.objects.get(user=request.user)
        return author in obj.authors.all()
