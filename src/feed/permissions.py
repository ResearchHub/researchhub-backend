from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class CanViewUserActivity(BasePermission):
    """
    Restrict a user's activity feed to that user, moderators, and hub editors.
    """

    message = "Cannot view another user's activity."

    def has_permission(self, request: Request, view) -> bool:
        """Return whether the requester may read the requested user's activity."""
        # An omitted user_id is a validation error, so let the query serializer
        # answer with 400 rather than masking it as 403 here.
        requested_user_id = request.query_params.get("user_id")
        if requested_user_id is None:
            return True

        return (
            requested_user_id == str(request.user.id)
            or request.user.is_moderator_or_editor()
        )
