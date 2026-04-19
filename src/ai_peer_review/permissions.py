from ai_peer_review.models import ProposalReview, RFPSummary
from ai_peer_review.services.report_access import (
    is_editor_or_moderator,
    user_can_view_proposal_review,
    user_can_view_rfp_summary,
)
from utils.permissions import AuthorizationBasedPermission


class AIPeerReviewPermission(AuthorizationBasedPermission):
    """
    Request-level: authenticated hub editor or moderator (see _can_use_ai_peer_review).
    Object-level:

    - ``ProposalReview`` / ``RFPSummary``: same — hub editors and moderators only.
    """

    message = "Not allowed to use AI peer review features."

    def has_permission(self, request, view):
        return self.is_authorized(request, view, obj=None)

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, ProposalReview):
            return user_can_view_proposal_review(request.user, obj)
        if isinstance(obj, RFPSummary):
            return user_can_view_rfp_summary(request.user, obj)
        return super().has_object_permission(request, view, obj)

    def is_authorized(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return self._can_use_ai_peer_review(request.user)

    def _can_use_ai_peer_review(self, user):
        return is_editor_or_moderator(user)
