from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from user.models import User


def _schedule_key_insights_after_assessed_update(comment, updated: int) -> None:
    """Bulk ``.update()`` does not emit ``post_save`` on Review; enqueue key-insights."""
    if not updated:
        return
    try:
        ud = comment.unified_document
    except Exception:
        ud = None
    if ud is None:
        return
    uid = ud.id

    def _enqueue(u=uid):
        from ai_peer_review.tasks import auto_run_proposal_key_insights_for_ud

        auto_run_proposal_key_insights_for_ud.delay(u, force=False)

    transaction.on_commit(_enqueue)


@receiver(post_save, sender=Purchase, dispatch_uid="review_assessed_on_purchase")
def mark_review_assessed_on_purchase(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.content_type.model != "rhcommentmodel":
        return
    if not User.is_rh_community_account(instance.user):
        return
    comment = instance.item
    if comment is None:
        return
    updated = comment.reviews.filter(is_assessed=False).update(is_assessed=True)
    _schedule_key_insights_after_assessed_update(comment, updated)


@receiver(
    post_save, sender=BountySolution, dispatch_uid="review_assessed_on_bounty_award"
)
def mark_review_assessed_on_bounty_award(sender, instance, **kwargs):
    if instance.status != BountySolution.Status.AWARDED:
        return
    if instance.content_type.model != "rhcommentmodel":
        return
    if not User.is_rh_community_account(instance.bounty.created_by):
        return
    comment = instance.item
    if comment is None:
        return
    updated = comment.reviews.filter(is_assessed=False).update(is_assessed=True)
    _schedule_key_insights_after_assessed_update(comment, updated)
