from django.template.loader import render_to_string

from mailing_list.services import EmailService
from purchase.models import Fundraise, Grant, GrantApplication
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.services.work_cover_service_for_email import build_work_cover

AWARD_PROPOSAL_ON_FUNDING_GRANT = (
    "This proposal is linked to an award grant and cannot apply to a funding grant."
)
FUNDING_PROPOSAL_ON_AWARD_GRANT = (
    "This proposal is linked to a funding grant and cannot apply to an award grant."
)
FUNDED_PROPOSAL_ON_AWARD_GRANT = (
    "This proposal has already raised funds and cannot apply to an award grant."
)
CLOSED_FUNDRAISE_ON_AWARD_GRANT = (
    "This proposal's fundraise is not open and cannot apply to an award grant."
)
EXPIRED_FUNDRAISE_ON_AWARD_GRANT = (
    "This proposal's fundraise has expired and cannot apply to an award grant."
)


class GrantApplicationService:
    """Handle grant applications and notice to the grant owner."""

    def __init__(self, email_service: EmailService | None = None) -> None:
        """Configure email delivery for grant applications."""
        self._emails = email_service or EmailService()

    def funding_application_error(
        self, grant: Grant, post: ResearchhubPost
    ) -> str | None:
        """Reject a proposal that would mix award and funding on one fundraise."""
        if grant.funding_mechanism == Grant.AWARD:
            if post.grant_applications.filter(
                grant__funding_mechanism=Grant.FUNDING
            ).exists():
                return FUNDING_PROPOSAL_ON_AWARD_GRANT
            return self._award_fundraise_error(post)
        if post.grant_applications.filter(
            grant__funding_mechanism=Grant.AWARD
        ).exists():
            return AWARD_PROPOSAL_ON_FUNDING_GRANT
        return None

    @staticmethod
    def _award_fundraise_error(post: ResearchhubPost) -> str | None:
        fundraises = Fundraise.objects.filter(
            unified_document_id=post.unified_document_id
        )
        open_fundraise = (
            fundraises.filter(status=Fundraise.OPEN)
            .select_related("escrow")
            .order_by("-created_date")
            .first()
        )
        if open_fundraise is None:
            if fundraises.exists():
                return CLOSED_FUNDRAISE_ON_AWARD_GRANT
            return None
        if open_fundraise.has_received_funding():
            return FUNDED_PROPOSAL_ON_AWARD_GRANT
        if open_fundraise.is_expired():
            return EXPIRED_FUNDRAISE_ON_AWARD_GRANT
        return None

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
                "email_activity_card.html",
                {
                    "author": applicant.author_profile,
                    "action": "Submitted a proposal for funding",
                    "created_date": application.created_date,
                    "cover": build_work_cover(proposal),
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
