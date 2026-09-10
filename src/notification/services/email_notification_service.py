from django.utils.html import format_html

from mailing_list.services import EmailService
from notification.models import Notification

BRANDED_TEMPLATE = "general_branded_email"


class EmailNotificationService:
    """Email recipients about the in-app notifications they receive."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Use the standard email service unless a client is provided."""
        self._email_service = email_service or EmailService()

    def send_grant_application_email(self, notification_id: int) -> None:
        """Email the RFP owner the applicant's name and a link to the proposal."""
        notification = Notification.objects.select_related(
            "action_user", "recipient", "unified_document"
        ).get(id=notification_id)
        self._send(
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

    def _send(
        self,
        notification: Notification,
        *,
        subject: str,
        body: str,
        cta_label: str,
    ) -> None:
        """Render the notification into the branded template and mail its recipient."""
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
