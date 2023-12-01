from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsModeratorOrReadOnly(BasePermission):
    """
    Allows read-only permissions to any request,
    but only allows write permissions to authenticated users who are moderators.
    """

    def has_permission(self, request, view):
        # Check if it's a read-only request
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        # Only allow write requests if the user is authenticated and a moderator
        return bool(user and user.is_authenticated and user.moderator)
