from notification.services import NotificationService
from researchhub.celery import QUEUE_NOTIFICATION, app


@app.task(queue=QUEUE_NOTIFICATION)
def email_notification_recipients(
    notification_ids: list[int], subject: str, message: str
) -> None:
    """Email the recipients of an existing notification audience."""
    NotificationService().email_recipients(notification_ids, subject, message)
