from utils.permissions import AuthorizationBasedPermission


class AIPeerReviewPermission(AuthorizationBasedPermission):
    """
    Permission for AI peer review / RFP summary features.
    Compose with UserIsEditor | IsModerator in views.
    """

    message = "Not allowed to use AI peer review features."

    def has_permission(self, request, view):
        return self.is_authorized(request, view, obj=None)

    def is_authorized(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return self._can_use_ai_peer_review(request.user)

    def _can_use_ai_peer_review(self, user):
        return True
