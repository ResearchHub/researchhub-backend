from purchase.models import Grant
from utils.permissions import AuthorizationBasedPermission


class ResearchAIPermission(AuthorizationBasedPermission):
    """
    Placeholder permission for Research AI features.
    For now: allows any authenticated user. Compose with UserIsEditor | IsModerator
    in views for editor/moderator access, e.g.:
        permission_classes = [ResearchAIPermission, UserIsEditor | IsModerator]
    Future: Add business logic here (min funded, subscription tier, credits).
    """

    message = "Not allowed to use Research AI features."

    def has_permission(self, request, view):
        return self.is_authorized(request, view, obj=None)

    def is_authorized(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return self._can_use_research_ai(request.user)

    def _can_use_research_ai(self, user):
        # Placeholder - expand with business logic later
        # e.g., check minimum funding, subscription, credits
        return True


def can_manage_grant(user, grant) -> bool:
    """Moderator, grant creator, or listed grant contact."""
    if getattr(user, "moderator", False):
        return True
    if grant.created_by_id == user.id:
        return True
    return grant.contacts.filter(id=user.id).exists()


def can_view_invited_experts_list(user, *, unified_document_id: int | None) -> bool:
    """
    Global expert list: hub editor or moderator.
    Grant-scoped list: grant creator/contacts/moderator.
    Other document-scoped list: hub editor or moderator.
    """
    if not getattr(user, "is_authenticated", False):
        return False

    if unified_document_id is None:
        return getattr(user, "moderator", False) or user.is_hub_editor()

    grant = Grant.objects.filter(unified_document_id=unified_document_id).first()
    if grant is not None:
        return can_manage_grant(user, grant)

    return getattr(user, "moderator", False) or user.is_hub_editor()
