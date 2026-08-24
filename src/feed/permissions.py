from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from feed.serializers import UserActivityQuerySerializer


class CanViewUserActivity(BasePermission):
    """
    Restrict a user's activity feed to that user, moderators, and hub editors.
    """

    message = "Cannot view another user's activity."

    def has_permission(self, request: Request, view) -> bool:
        """Return whether the requester may read the requested user's activity."""
        # Parse with the view's serializer so the ownership check compares the
        # same integer the view will, and invalid input reaches the view's 400
        # rather than being masked as a 403 here.
        query = UserActivityQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return True

        return (
            query.validated_data["user_id"] == request.user.id
            or request.user.is_moderator_or_editor()
        )
