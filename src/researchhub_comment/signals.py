from logging import Logger

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from notification.models import Notification
from researchhub_comment.constants.rh_comment_thread_types import AUTHOR_UPDATE
from researchhub_comment.models import RhCommentModel
from researchhub_comment.tasks import send_author_update_email_notifications
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.follow_model import Follow

logger = Logger(__name__)


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
