from notification.models import Notification
from notification.services import NotificationService
from researchhub.celery import QUEUE_NOTIFICATION, app


@app.task(queue=QUEUE_NOTIFICATION)
def email_notification_recipients(
    notification_ids: list[int], subject: str, message: str
) -> None:
    """
    Email everyone the given notifications were sent to.

    Lets signals and views notify people by email without blocking on the send.
    """
    notifications = NotificationService()
    pending = Notification.objects.filter(id__in=notification_ids).select_related(
        "recipient", "unified_document"
    )

    for notification in pending:
        notifications.email_recipient(notification, subject, message)
