import time
from datetime import datetime
from logging import Logger

import pytz
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from notification.models import Notification
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import create_preregistration_update_reward_distribution
from reputation.distributor import Distributor
from reputation.related_models.distribution import Distribution as DistributionModel
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_comment.tasks import send_author_update_email_notifications
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.follow_model import Follow

logger = Logger(__name__)

PREREGISTRATION_UPDATE_REWARD_AMOUNT_USD = 50


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


@receiver(
    post_save, sender=RhCommentModel, dispatch_uid="reward_preregistration_update"
)
def reward_preregistration_update(sender, instance, created, **kwargs):
    """
    Reward preregistration authors with $50 USD in RSC when they post an
    author update on a preregistration with a COMPLETED fundraise, provided
    they received a monthly reminder this calendar month and haven't already
    been rewarded this month for that fundraise.
    """
    if not created:
        return

    if instance.thread.thread_type != AUTHOR_UPDATE:
        return

    try:
        _reward_preregistration_update(instance)
    except Exception as e:
        logger.error(f"Failed to reward preregistration update: {e}")


def _reward_preregistration_update(comment: RhCommentModel):
    document = comment.unified_document.get_document()

    if not (
        isinstance(document, ResearchhubPost)
        and document.document_type == PREREGISTRATION
    ):
        return

    author = comment.created_by
    unified_document = comment.unified_document
    now = datetime.now(pytz.UTC)

    completed_fundraises = Fundraise.objects.filter(
        unified_document=unified_document,
        created_by=author,
        status=Fundraise.COMPLETED,
    )

    fundraise_ct = ContentType.objects.get_for_model(Fundraise)

    for fundraise in completed_fundraises:
        reminder_sent = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE_REMINDER,
            recipient=author,
            content_type=fundraise_ct,
            object_id=fundraise.id,
            created_date__year=now.year,
            created_date__month=now.month,
        ).exists()

        if not reminder_sent:
            continue

        already_rewarded = DistributionModel.objects.filter(
            recipient=author,
            distribution_type="PREREGISTRATION_UPDATE_REWARD",
            proof_item_content_type=fundraise_ct,
            proof_item_object_id=fundraise.id,
            created_date__year=now.year,
            created_date__month=now.month,
        ).exists()

        if already_rewarded:
            continue

        rsc_amount = RscExchangeRate.usd_to_rsc(
            PREREGISTRATION_UPDATE_REWARD_AMOUNT_USD
        )
        distribution = create_preregistration_update_reward_distribution(rsc_amount)
        distributor = Distributor(
            distribution=distribution,
            recipient=author,
            db_record=fundraise,
            timestamp=time.time(),
        )
        distributor.distribute()
