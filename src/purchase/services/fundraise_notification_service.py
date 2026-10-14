from django.db.models import Q, QuerySet
from django.template.loader import render_to_string

from mailing_list.services import EmailService, truncate_preview
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import Purchase, RscExchangeRate, UsdFundraiseContribution
from purchase.related_models.constants.currency import USD
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.models import User


class FundraiseNotificationService:
    """Notify proposal and grant authors about contributions to their funding."""

    def __init__(
        self,
        notification_service: NotificationService | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        """Configure notification and email delivery for contributions."""
        self._notifications = notification_service or NotificationService()
        self._emails = email_service or EmailService()

    def notify_contribution_authors(self, contribution_id: int, currency: str) -> None:
        """Notify proposal authors after a successful contribution commits."""
        if currency == USD:
            contribution = UsdFundraiseContribution.objects.select_related(
                "user", "fundraise__unified_document"
            ).get(id=contribution_id)
            fundraise = contribution.fundraise
            usd_amount = contribution.amount_cents / 100
            rsc_amount = str(RscExchangeRate.usd_to_rsc(usd_amount))
        else:
            contribution = Purchase.objects.select_related("user").get(
                id=contribution_id
            )
            fundraise = contribution.item
            rsc_amount = contribution.amount

        proposal = fundraise.unified_document.get_document()
        recipients = self._notify_recipients(
            Notification.FUNDRAISE_CONTRIBUTION,
            contribution,
            rsc_amount,
            proposal,
            recipients=User.objects.filter(
                Q(id=proposal.created_by_id)
                | Q(
                    author_profile__authored_posts=proposal,
                    author_profile__is_removed=False,
                )
            ).distinct(),
        )
        self._emails.send_message_email(
            [recipient.email for recipient in recipients],
            "New contribution to your proposal",
            f"{contribution.user.full_name()} submitted a contribution to your "
            f"proposal: {proposal.title}.",
            link=proposal.unified_document.frontend_view_link(),
        )

    def notify_grant_authors(self, purchase_id: int) -> None:
        """Notify the RFP creator and contacts after a pool contribution commits."""
        purchase = Purchase.objects.select_related("user").get(id=purchase_id)
        grant = purchase.item.grant
        grant_post = grant.unified_document.get_document()

        recipients = self._notify_recipients(
            Notification.FUNDING_POOL_CONTRIBUTION,
            purchase,
            purchase.amount,
            grant_post,
            recipients=User.objects.filter(
                Q(id=grant.created_by_id) | Q(grant_contacts=grant)
            ).distinct(),
        )
        message = render_to_string(
            "email_content_card.html",
            {
                "author": grant.created_by.author_profile,
                "action": "RFP",
                "possessive": True,
                "title": grant_post.title,
                "created_date": grant_post.created_date,
                "body": truncate_preview(grant_post.renderable_text),
            },
        )
        for recipient in recipients:
            self._emails.send_message_email(
                [recipient.email],
                f"Congratulations {recipient.first_name}, "
                f"{purchase.user.full_name()} contributed to your RFP!",
                message,
                link=grant.unified_document.frontend_view_link(),
                is_html=True,
            )

    def _notify_recipients(
        self,
        notification_type: str,
        contribution: Purchase | UsdFundraiseContribution,
        rsc_amount: str,
        post: ResearchhubPost,
        recipients: QuerySet[User],
    ) -> list[User]:
        """Send each recipient an in-app alert with the RSC amount and return them."""
        recipients = list(recipients)
        for recipient in recipients:
            self._notifications.try_send(
                notification_type,
                recipient=recipient,
                action_user=contribution.user,
                item=contribution,
                unified_document=post.unified_document,
                extra={"amount": rsc_amount},
            )
        return recipients
