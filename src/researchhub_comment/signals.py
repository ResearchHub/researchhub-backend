import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from discussion.models import Vote
from notification.models import Notification
from purchase.models import Purchase
from reputation.models import BountySolution
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_comment.tasks import send_author_update_email_notifications, update_comment_academic_score
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import UserVerification
from user.related_models.follow_model import Follow

logger = logging.getLogger(__name__)


@receiver(
    post_save, sender=RhCommentModel, dispatch_uid="create_rh_comment_notifiation"
)
def create_thread_notification(sender, instance, created, **kwargs):
    if created:
        creator = instance.created_by
        if instance.parent:
            notification_type = Notification.COMMENT_ON_COMMENT
        else:
            notification_type = Notification.COMMENT

        for recipient in instance.users_to_notify:
            if recipient and recipient != creator:
                notification = Notification.objects.create(
                    item=instance,
                    unified_document=instance.unified_document,
                    notification_type=notification_type,
                    recipient=recipient,
                    action_user=creator,
                )
                notification.send_notification()


@receiver(
    post_save, sender=RhCommentModel, dispatch_uid="create_author_update_notification"
)
def create_author_update_notification(sender, instance, created, **kwargs):
    """
    Signal handler for creating author update notifications when update comments
    are created on preregistrations.
    """
    if not created:
        logger.debug("Not a new comment")
        return

    if instance.thread.thread_type != AUTHOR_UPDATE:
        logger.debug("Not an author update thread")
        return

    try:
        _create_author_update_notification(instance)
    except Exception as e:
        logger.error(f"Failed to create author update notification: {e}")


def _create_author_update_notification(comment: RhCommentModel):
    document = comment.unified_document.get_document()

    if not (
        isinstance(document, ResearchhubPost)
        and document.document_type == PREREGISTRATION
    ):
        logger.debug("Not a preregistration")
        return

    follower_user_ids = []
    follows = Follow.objects.filter(
        content_type=ContentType.objects.get_for_model(document),
        object_id=document.id,
    )
    for follow in follows:
        notification = Notification.objects.create(
            item=comment,
            unified_document=comment.unified_document,
            notification_type=Notification.PREREGISTRATION_UPDATE,
            recipient=follow.user,
            action_user=comment.created_by,
        )
        notification.send_notification()
        follower_user_ids.append(follow.user.id)

    if follower_user_ids:
        send_author_update_email_notifications.delay(comment.id, follower_user_ids)


@receiver(post_save, sender=Vote, dispatch_uid="update_comment_score_on_vote")
def handle_comment_vote_for_scoring(sender, instance, created, **kwargs):
    """Update academic score when a comment receives votes."""
    if instance.content_type.model == "rhcommentmodel":
        from django.db import transaction
        transaction.on_commit(
            lambda: update_comment_academic_score.apply_async(
                (instance.object_id,),
                priority=2,
                countdown=5
            )
        )


@receiver(post_delete, sender=Vote, dispatch_uid="update_comment_score_on_vote_delete")
def handle_comment_vote_delete_for_scoring(sender, instance, **kwargs):
    """Update academic score when a vote is removed from a comment."""
    if instance.content_type.model == "rhcommentmodel":
        from django.db import transaction
        transaction.on_commit(
            lambda: update_comment_academic_score.apply_async(
                (instance.object_id,),
                priority=2,
                countdown=5
            )
        )


@receiver(post_save, sender=Purchase, dispatch_uid="update_comment_score_on_tip")
def handle_comment_tip_for_scoring(sender, instance, created, **kwargs):
    """Update academic score when a comment receives tips (BOOST purchases)."""
    if (instance.purchase_type == Purchase.BOOST and 
        instance.content_type.model == "rhcommentmodel"):
        from django.db import transaction
        transaction.on_commit(
            lambda: update_comment_academic_score.apply_async(
                (instance.object_id,),
                priority=2,
                countdown=5
            )
        )


@receiver(post_save, sender=BountySolution, dispatch_uid="update_comment_score_on_bounty_award")
def handle_comment_bounty_award_for_scoring(sender, instance, created, **kwargs):
    """Update academic score when a comment receives a bounty award."""
    if (instance.status == BountySolution.Status.AWARDED and
        instance.content_type.model == "rhcommentmodel"):
        from django.db import transaction
        transaction.on_commit(
            lambda: update_comment_academic_score.apply_async(
                (instance.object_id,),
                priority=2,
                countdown=5
            )
        )


@receiver(post_save, sender=UserVerification, dispatch_uid="update_comment_scores_on_verification")
def handle_user_verification_change_for_scoring(sender, instance, created, **kwargs):
    """Update all comment scores when user verification status changes."""
    if instance.status == UserVerification.Status.APPROVED:
        from django.db import transaction
        from researchhub_comment.tasks import check_stale_comment_scores
        # Queue batch update for all user's comments
        transaction.on_commit(
            lambda: check_stale_comment_scores.apply_async(
                kwargs={'user_id': instance.user_id},
                priority=3,
                countdown=10
            )
        )
