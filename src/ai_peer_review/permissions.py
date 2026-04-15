from ai_peer_review.models import ProposalReview
from ai_peer_review.services.report_access import (
    user_can_view_grant_comparison,
    user_can_view_proposal_review,
)
from purchase.models import Grant
from utils.permissions import AuthorizationBasedPermission


class AIPeerReviewPermission(AuthorizationBasedPermission):
    """
    Request-level: authenticated + feature gate (see _can_use_ai_peer_review).
    Object-level: proposal review visibility (author, grant owner, entitlement,
    editors).
    """

    message = "Not allowed to use AI peer review features."

    def has_permission(self, request, view):
        return self.is_authorized(request, view, obj=None)

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, ProposalReview):
            return user_can_view_proposal_review(request.user, obj)
        if isinstance(obj, Grant):
            return user_can_view_grant_comparison(request.user, obj)
        return super().has_object_permission(request, view, obj)

    def is_authorized(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return self._can_use_ai_peer_review(request.user)

    # TODO: Add business logic here
    def _can_use_ai_peer_review(self, user):
        return True
