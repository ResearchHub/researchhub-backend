import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from notification.models import Notification
from purchase.related_models.grant_application_model import GrantApplication

logger = logging.getLogger(__name__)


@receiver(
    post_save,
    sender=GrantApplication,
    dispatch_uid="notify_grant_owner_on_application",
)
def notify_grant_owner_on_application(sender, instance, created, **kwargs):
    """Notify the RFP owner when a new proposal is submitted to their grant."""
    if not created:
        return

    try:
        grant = instance.grant
        recipient = grant.created_by
        action_user = instance.applicant

        if not recipient or recipient == action_user:
            return

        unified_document = instance.preregistration_post.unified_document
        if unified_document is None:
            unified_document = grant.unified_document

        notification = Notification.objects.create(
            notification_type=Notification.GRANT_APPLICATION_SUBMITTED,
            recipient=recipient,
            action_user=action_user,
            content_type=ContentType.objects.get_for_model(instance),
            object_id=instance.id,
            unified_document=unified_document,
        )
        transaction.on_commit(notification.send_notification)
    except Exception:
        logger.exception(
            "Failed to send GRANT_APPLICATION_SUBMITTED notification for "
            "GrantApplication %s",
            instance.id,
        )
