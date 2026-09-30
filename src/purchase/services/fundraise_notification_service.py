from decimal import Decimal

from django.db.models import Q

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import Purchase, UsdFundraiseContribution
from purchase.related_models.constants.currency import USD
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
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

        self._notify_document_authors(
            Notification.FUNDRAISE_CONTRIBUTION,
            contribution,
            fundraise.unified_document,
            extra={"amount": str(amount), "currency": currency},
            subject="New contribution to your proposal",
            message=f"{action} {amount:,.2f} {currency} to your proposal",
        )

    def notify_grant_authors(self, purchase_id: int) -> None:
        """Notify grant authors after a funding pool contribution commits."""
        purchase = Purchase.objects.select_related("user").get(id=purchase_id)
        amount = Decimal(purchase.amount)

        self._notify_document_authors(
            Notification.FUNDING_POOL_CONTRIBUTION,
            purchase,
            purchase.item.grant.unified_document,
            extra={"amount": str(amount)},
            subject="New contribution to your funding opportunity",
            message=f"contributed {amount:,.2f} RSC to your funding opportunity",
        )

    def _notify_document_authors(
        self,
        notification_type: str,
        contribution: Purchase | UsdFundraiseContribution,
        document: ResearchhubUnifiedDocument,
        extra: dict[str, str],
        subject: str,
        message: str,
    ) -> None:
        """Send in-app and email alerts to the document's creator and authors."""
        post = document.get_document()
        recipients = User.objects.filter(
            Q(id=post.created_by_id)
            | Q(author_profile__authored_posts=post, author_profile__is_removed=False)
        ).distinct()
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
