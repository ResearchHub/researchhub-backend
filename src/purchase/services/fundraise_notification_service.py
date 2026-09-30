from decimal import Decimal

from django.db.models import Q, QuerySet

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import Purchase, UsdFundraiseContribution
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
            amount = Decimal(contribution.amount_cents) / 100
            action = "submitted a contribution of"
        else:
            contribution = Purchase.objects.select_related("user").get(
                id=contribution_id
            )
            fundraise = contribution.item
            amount = Decimal(contribution.amount)
            action = "contributed"

        proposal = fundraise.unified_document.get_document()
        self._notify_recipients(
            Notification.FUNDRAISE_CONTRIBUTION,
            contribution,
            proposal,
            recipients=User.objects.filter(
                Q(id=proposal.created_by_id)
                | Q(
                    author_profile__authored_posts=proposal,
                    author_profile__is_removed=False,
                )
            ).distinct(),
            extra={"amount": str(amount), "currency": currency},
            subject="New contribution to your proposal",
            message=f"{action} {amount:,.2f} {currency} to your proposal",
        )

    def notify_grant_authors(self, purchase_id: int) -> None:
        """Notify the RFP creator and contacts after a pool contribution commits."""
        purchase = Purchase.objects.select_related("user").get(id=purchase_id)
        grant = purchase.item.grant
        amount = Decimal(purchase.amount)

        self._notify_recipients(
            Notification.FUNDING_POOL_CONTRIBUTION,
            purchase,
            grant.unified_document.get_document(),
            recipients=User.objects.filter(
                Q(id=grant.created_by_id) | Q(grant_contacts=grant)
            ).distinct(),
            extra={"amount": str(amount)},
            subject="New contribution to your RFP",
            message=f"contributed {amount:,.2f} RSC to your RFP",
        )

    def _notify_recipients(
        self,
        notification_type: str,
        contribution: Purchase | UsdFundraiseContribution,
        post: ResearchhubPost,
        recipients: QuerySet[User],
        extra: dict[str, str],
        subject: str,
        message: str,
    ) -> None:
        """Send in-app and email alerts once to each recipient."""
        document = post.unified_document
        recipients = list(recipients)
        for recipient in recipients:
            self._notifications.try_send(
                notification_type,
                recipient=recipient,
                action_user=contribution.user,
                item=contribution,
                unified_document=document,
                extra=extra,
            )

        self._emails.send_message_email(
            [recipient.email for recipient in recipients],
            subject,
            f"{contribution.user.full_name()} {message}: {post.title}.",
            link=document.frontend_view_link(),
        )
