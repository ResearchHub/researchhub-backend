from rest_framework.request import Request

from user.models import Author
from utils.permissions import AuthorizationBasedPermission, RuleBasedPermission


class UpdatePaper(RuleBasedPermission):
    message = "Not enough reputation to update paper."

    def satisfies_rule(self, request: Request) -> bool:
        """Return whether the requester may update a paper."""
        return request.user.reputation >= 1 and not request.user.is_suspended


class IsAuthor(AuthorizationBasedPermission):
    message = "User is not authorized."

    def is_authorized(self, request, view, obj):
        author = Author.objects.get(user=request.user)
        return author in obj.authors.all()
