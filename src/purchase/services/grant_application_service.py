from django.utils.html import format_html

from mailing_list.services import EmailService
from purchase.models import GrantApplication


class GrantApplicationService:
    """Handle communication about grant applications."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Configure email delivery for grant applications."""
        self._emails = email_service or EmailService()

    def send_application_email(self, application_id: int) -> None:
        """Email the grant owner the applicant's name and proposal link."""
        application = GrantApplication.objects.select_related(
            "applicant",
            "grant__created_by",
            "grant__unified_document",
            "preregistration_post__unified_document",
        ).get(id=application_id)
        document = application.preregistration_post.unified_document
        if document is None:
            document = application.grant.unified_document

        subject = "Someone applied to your RFP"
        context = {
            "subject": subject,
            "body": format_html(
                "<p>A new research proposal has been submitted</p>"
                "<p>{} submitted proposal: {}</p>",
                application.applicant.first_name,
                document.get_display_title(),
            ),
            "cta_url": document.frontend_view_link(),
            "cta_label": "View Proposal",
        }
        self._emails.send_email(
            [application.grant.created_by.email],
            subject,
            context,
            template="general_branded_email",
        )
