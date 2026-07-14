import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from notification.models import Notification
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from review.models.review_model import Review
from user.models import User

logger = logging.getLogger(__name__)


def _schedule_key_insights_after_assessed_update(comment, updated: int) -> None:
    """Enqueue key insights after bulk-marking reviews assessed."""
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

        auto_run_proposal_key_insights_for_ud.delay(u, force=True)

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


@receiver(
    post_save,
    sender=Review,
    dispatch_uid="notify_grant_owner_on_proposal_review",
)
def notify_grant_owner_on_proposal_review(sender, instance, created, **kwargs):
    """Notify RFP owners when a peer-review score is created on a linked proposal."""
    if not created or not instance.unified_document_id:
        return

    try:
        applications = (
            GrantApplication.objects.filter(
                preregistration_post__unified_document_id=instance.unified_document_id
            )
            .select_related("grant", "grant__created_by")
            .distinct()
        )

        action_user = instance.created_by
        if not action_user:
            return

        review_ct = ContentType.objects.get_for_model(instance)
        notified_recipient_ids = set()

        for application in applications:
            recipient = application.grant.created_by
            if (
                not recipient
                or recipient == action_user
                or recipient.id in notified_recipient_ids
            ):
                continue

            notification = Notification.objects.create(
                notification_type=Notification.PROPOSAL_PEER_REVIEW,
                recipient=recipient,
                action_user=action_user,
                content_type=review_ct,
                object_id=instance.id,
                unified_document=instance.unified_document,
            )
            transaction.on_commit(notification.send_notification)
            notified_recipient_ids.add(recipient.id)
    except Exception:
        logger.exception(
            "Failed to send PROPOSAL_PEER_REVIEW notification for Review %s",
            instance.id,
        )
