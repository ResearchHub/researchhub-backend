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
        self._notify_recipients(
            Notification.FUNDRAISE_CONTRIBUTION,
            contribution,
            rsc_amount,
            proposal,
            "Proposal",
            recipients=User.objects.filter(
                Q(id=proposal.created_by_id)
                | Q(
                    author_profile__authored_posts=proposal,
                    author_profile__is_removed=False,
                )
            ).distinct(),
        )

    def notify_grant_authors(self, purchase_id: int) -> None:
        """Notify the RFP creator and contacts after a pool contribution commits."""
        purchase = Purchase.objects.select_related("user").get(id=purchase_id)
        grant = purchase.item.grant
        self._notify_recipients(
            Notification.FUNDING_POOL_CONTRIBUTION,
            purchase,
            purchase.amount,
            grant.unified_document.get_document(),
            "RFP",
            recipients=User.objects.filter(
                Q(id=grant.created_by_id) | Q(grant_contacts=grant)
            ).distinct(),
        )

    def _notify_recipients(
        self,
        notification_type: str,
        contribution: Purchase | UsdFundraiseContribution,
        rsc_amount: str,
        post: ResearchhubPost,
        label: str,
        recipients: QuerySet[User],
    ) -> None:
        """Send each recipient an in-app alert and a congratulatory email."""
        message = render_to_string(
            "email_content_card.html",
            {
                "author": post.created_by.author_profile,
                "action": label,
                "possessive": True,
                "title": post.title,
                "created_date": post.created_date,
                "body": truncate_preview(post.renderable_text),
            },
        )
        for recipient in recipients:
            self._notifications.try_send(
                notification_type,
                recipient=recipient,
                action_user=contribution.user,
                item=contribution,
                unified_document=post.unified_document,
                extra={"amount": rsc_amount},
            )
            self._emails.send_message_email(
                [recipient.email],
                f"Congratulations {recipient.first_name}, "
                f"{contribution.user.full_name()} contributed to your {label}!",
                message,
                link=post.unified_document.frontend_view_link(),
                is_html=True,
            )
