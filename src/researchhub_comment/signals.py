from django.db.models.signals import post_save
from django.dispatch import receiver

from notification.models import Notification
from researchhub_comment.models import RhCommentModel


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
