from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from paper.models import Paper
from paper.related_models.paper_version import PaperVersion
from user.models import Author
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


def is_legacy_journal_paper(paper: Paper) -> bool:
    """Return whether a paper belongs to the retired ResearchHub Journal."""
    return PaperVersion.objects.filter(
        paper_id=paper.id,
        journal=PaperVersion.RESEARCHHUB,
    ).exists()


class CreatePaper(RuleBasedPermission):
    message = "Not enough reputation to upload paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class UpdatePaper(RuleBasedPermission):
    message = "Not enough reputation to upload paper."

    def satisfies_rule(self, request):
        return request.user.reputation >= 1 and not request.user.is_suspended


class CanModifyLegacyJournalPaper(BasePermission):
    """Allow legacy journal papers to be read but not modified."""

    message = "Legacy journal papers are read-only."

    def has_object_permission(
        self,
        request: Request,
        view: APIView,
        obj: Paper,
    ) -> bool:
        """Reject unsafe requests that target a retired journal paper."""
        return request.method in SAFE_METHODS or not is_legacy_journal_paper(obj)


class IsAuthor(AuthorizationBasedPermission):
    message = "User is not authorized."

    def is_authorized(self, request, view, obj):
        author = Author.objects.get(user=request.user)
        return author in obj.authors.all()
