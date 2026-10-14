from django.template.loader import render_to_string

from mailing_list.services import EmailService, truncate_preview
from purchase.models import GrantApplication


class GrantApplicationService:
    """Handle communication about grant applications."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Configure email delivery for grant applications."""
        self._emails = email_service or EmailService()

    def send_application_email(self, application_id: int) -> None:
        """Email the grant owner a preview card of the applicant's proposal."""
        application = GrantApplication.objects.select_related(
            "applicant__author_profile",
            "grant__created_by",
            "grant__unified_document",
            "preregistration_post__unified_document",
        ).get(id=application_id)
        applicant = application.applicant
        proposal = application.preregistration_post
        document = proposal.unified_document
        if document is None:
            document = application.grant.unified_document

        subject = (
            f"{applicant.full_name()} has applied to your RFP "
            f"{application.grant.unified_document.get_display_title()}"
        )
        context = {
            "subject": subject,
            "body": render_to_string(
                "email_content_card.html",
                {
                    "author": applicant.author_profile,
                    "action": "submitted a proposal",
                    "title": proposal.title,
                    "created_date": application.created_date,
                    "body": truncate_preview(proposal.renderable_text),
                },
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
