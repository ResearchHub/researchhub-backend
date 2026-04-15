from ai_peer_review.models import ProposalReview, ReportEntitlement
from purchase.related_models.purchase_model import Purchase


def is_editor_or_moderator(user) -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "moderator", False):
        return True
    return user.is_hub_editor()


def user_can_view_proposal_review(user, review: ProposalReview) -> bool:
    if not user.is_authenticated:
        return False
    if is_editor_or_moderator(user):
        return True
    owner = review.unified_document.created_by
    if owner and owner.id == user.id:
        return True
    if review.grant_id and review.grant.created_by_id == user.id:
        return True
    return ReportEntitlement.objects.filter(
        user=user,
        proposal_review=review,
        purchase__paid_status=Purchase.PAID,
    ).exists()


def user_can_view_grant_comparison(user, grant) -> bool:
    if not user.is_authenticated:
        return False
    if is_editor_or_moderator(user):
        return True
    return grant.created_by_id == user.id
