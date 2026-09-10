from mailing_list.services import EmailService
from notification.models import Notification

BRANDED_TEMPLATE = "general_branded_email"


class EmailNotificationService:
    """Email notification recipients using the shared branded template."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Use the standard email service unless a client is provided."""
        self._email_service = email_service or EmailService()

    def send_notification_email(
        self,
        notification: Notification,
        *,
        subject: str,
        body: str,
        cta_label: str,
    ) -> None:
        """Mail the notification's recipient the given copy and a link to the item."""
        self._email_service.send_email(
            recipients=notification.recipient.email,
            subject=subject,
            email_context={
                "subject": subject,
                "body": body,
                "cta_url": notification.navigation_url,
                "cta_label": cta_label,
            },
            template=BRANDED_TEMPLATE,
        )
