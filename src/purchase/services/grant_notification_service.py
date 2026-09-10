from django.utils.html import format_html

from notification.models import Notification
from notification.services import EmailNotificationService


class GrantNotificationService:
    """Email grant owners about activity on their RFPs."""

    def __init__(
        self, email_notifications: EmailNotificationService | None = None
    ) -> None:
        """Use the standard notification email service unless one is provided."""
        self._email_notifications = email_notifications or EmailNotificationService()

    def send_application_email(self, notification_id: int) -> None:
        """Email the RFP owner the applicant's name and a link to the proposal."""
        notification = Notification.objects.select_related(
            "action_user", "recipient", "unified_document"
        ).get(id=notification_id)
        self._email_notifications.send_notification_email(
            notification,
            subject="Someone applied to your RFP",
            body=format_html(
                "<p>A new research proposal has been submitted</p>"
                "<p>{} submitted proposal: {}</p>",
                notification.action_user.first_name,
                notification.unified_document.get_display_title(),
            ),
            cta_label="View Proposal",
        )
