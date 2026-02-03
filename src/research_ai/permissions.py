from utils.permissions import AuthorizationBasedPermission


class ResearchAIPermission(AuthorizationBasedPermission):
    """
    Placeholder permission for Research AI features.
    For now: allows any authenticated user. Compose with user.permissions.IsModerator
    in views for moderator-only access, e.g.:
        permission_classes = [ResearchAIPermission, IsModerator]
    Future: Add business logic here (min funded, subscription tier, credits).
    """

    message = "Not allowed to use Research AI features."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        # Placeholder - always allow for now; add business logic later
        return self._can_use_research_ai(request.user)

    def is_authorized(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return self._can_use_research_ai(request.user)

    def _can_use_research_ai(self, user):
        # Placeholder - expand with business logic later
        # e.g., check minimum funding, subscription, credits
        return True
