from ai_peer_review.models import ProposalReview, RFPSummary


def is_editor_or_moderator(user) -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "moderator", False):
        return True
    return user.is_hub_editor()


def user_can_view_proposal_review(user, _review: ProposalReview) -> bool:
    return is_editor_or_moderator(user)


def user_can_view_rfp_summary(user, _summary: RFPSummary) -> bool:
    return is_editor_or_moderator(user)
