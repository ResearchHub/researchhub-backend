from research_ai.services.usage_budget import resolve_ai_tier
from utils.permissions import AuthorizationBasedPermission


class ResearchAIPermission(AuthorizationBasedPermission):
    """Allow authenticated users whose resolved Research AI tier is not blocked."""

    message = "Not allowed to use Research AI features."

    def has_permission(self, request, view):
        return self.is_authorized(request, view, obj=None)

    def is_authorized(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return self._can_use_research_ai(request.user)

    def _can_use_research_ai(self, user):
        return resolve_ai_tier(user).name != "blocked"
