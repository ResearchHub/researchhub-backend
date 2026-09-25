import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from notification.models import Notification
from notification.services import NotificationService
from purchase.related_models.grant_application_model import GrantApplication
from purchase.tasks import send_grant_application_owner_email

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

        NotificationService().try_send(
            Notification.GRANT_APPLICATION_SUBMITTED,
            recipient=recipient,
            action_user=action_user,
            item=instance,
            unified_document=unified_document,
        )
        transaction.on_commit(
            lambda: send_grant_application_owner_email.delay(instance.id), robust=True
        )
    except Exception:
        logger.exception(
            "Failed to send GRANT_APPLICATION_SUBMITTED notification for "
            "GrantApplication %s",
            instance.id,
        )
