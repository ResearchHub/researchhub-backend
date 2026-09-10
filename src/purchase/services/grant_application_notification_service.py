from mailing_list.services import EmailService
from notification.models import Notification


class GrantApplicationNotificationService:
    """Send application emails using the existing in-app notification content."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Use the standard email service unless a client is provided."""
        self._email_service = email_service or EmailService()

    def send_application_email(self, notification_id: int) -> None:
        """Email the RFP owner the submitted proposal's notification and link."""
        notification = Notification.objects.select_related("recipient").get(
            id=notification_id
        )
        subject = "New Proposal Submitted to Your Funding Opportunity"
        self._email_service.send_email(
            recipients=notification.recipient.email,
            subject=subject,
            email_context={
                "subject": subject,
                "body": "".join(part["value"] for part in notification.body),
                "cta_url": notification.navigation_url,
                "cta_label": "View Proposal",
            },
            template="general_branded_email",
        )
