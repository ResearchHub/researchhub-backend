from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from user.models import Author
from utils.permissions import AuthorizationBasedPermission


class UpdatePaper(BasePermission):
    """
    Restrict paper writes to site moderators and hub editors.
    """

    message = "Only moderators and hub editors can update papers."

    def has_permission(self, request: Request, view) -> bool:
        """Return whether the requester may write to papers at all."""
        # Other write actions declare their own permissions.
        # `delete_user_vote` does not, so gating by HTTP method blocks removing a vote.
        if getattr(view, "action", None) not in ("partial_update", "update"):
            return True

        user = request.user
        return (
            user.is_authenticated
            and not user.is_suspended
            and user.is_moderator_or_editor()
        )


class IsAuthor(AuthorizationBasedPermission):
    message = "User is not authorized."

    def is_authorized(self, request, view, obj):
        author = Author.objects.get(user=request.user)
        return author in obj.authors.all()
