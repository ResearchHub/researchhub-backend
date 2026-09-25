from decimal import Decimal

from django.db.models import Q

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import Purchase, UsdFundraiseContribution
from purchase.related_models.constants.currency import USD
from user.models import User


class FundraiseNotificationService:
    """Notify proposal authors about fundraise contributions."""

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

        document = fundraise.unified_document
        proposal = document.get_document()
        recipients = User.objects.filter(
            Q(id=proposal.created_by_id)
            | Q(
                author_profile__authored_posts=proposal,
                author_profile__is_removed=False,
            )
        ).distinct()
        for recipient in recipients:
            self._notifications.try_send(
                Notification.FUNDRAISE_CONTRIBUTION,
                recipient=recipient,
                action_user=contribution.user,
                item=contribution,
                unified_document=document,
                extra={"amount": str(amount), "currency": currency},
            )

        self._emails.send_message_email(
            [recipient.email for recipient in recipients],
            "New contribution to your proposal",
            f"{contribution.user.full_name()} {action} {amount:,.2f} {currency} "
            f"to your proposal: {proposal.title}.",
            link=document.frontend_view_link(),
        )
