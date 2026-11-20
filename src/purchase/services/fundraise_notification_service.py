import logging
from decimal import Decimal

from django.db.models import Q, QuerySet
from django.template.loader import render_to_string

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import (
    Balance,
    Purchase,
    RscExchangeRate,
    UsdFundraiseContribution,
)
from purchase.related_models.constants.currency import USD
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.services.work_cover_service_for_email import (
    build_work_cover,
    format_compact_usd,
)
from user.models import User

logger = logging.getLogger(__name__)


class FundraiseNotificationService:
    """Notify authors about contributions and email contributors a receipt."""

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
                "user__author_profile", "fundraise__unified_document"
            ).get(id=contribution_id)
            fundraise = contribution.fundraise
            usd_amount = contribution.amount_cents / 100
            rsc_amount = str(RscExchangeRate.usd_to_rsc(usd_amount))
            receipt = (usd_amount, contribution.fee_cents / 100, "${:,.2f}")
        else:
            contribution = Purchase.objects.select_related(
                "user__author_profile", "funding_distribution"
            ).get(id=contribution_id)
            fundraise = contribution.item
            rsc_amount = contribution.amount
            usd_amount = float(rsc_amount) * contribution.rsc_usd_rate
            # A pool distribution moves pool funds, not the distributor's own.
            receipt = (
                None
                if hasattr(contribution, "funding_distribution")
                else self._rsc_receipt(contribution)
            )

        proposal = fundraise.unified_document.get_document()
        if receipt:
            self._send_receipt(contribution, proposal, "a proposal", *receipt)
        self._notify_recipients(
            Notification.FUNDRAISE_CONTRIBUTION,
            contribution,
            rsc_amount,
            usd_amount,
            proposal,
            action="Funded a proposal",
            label="proposal",
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
        purchase = Purchase.objects.select_related("user__author_profile").get(
            id=purchase_id
        )
        grant = purchase.item.grant
        rfp = grant.unified_document.get_document()
        self._send_receipt(purchase, rfp, "an RFP", *self._rsc_receipt(purchase))

        self._notify_recipients(
            Notification.FUNDING_POOL_CONTRIBUTION,
            purchase,
            purchase.amount,
            float(purchase.amount) * purchase.rsc_usd_rate,
            rfp,
            action="Added to an RFP’s funding pool",
            label="RFP",
            recipients=User.objects.filter(
                Q(id=grant.created_by_id) | Q(grant_contacts=grant)
            ).distinct(),
        )

    def _notify_recipients(
        self,
        notification_type: str,
        contribution: Purchase | UsdFundraiseContribution,
        rsc_amount: str,
        usd_amount: float,
        post: ResearchhubPost,
        action: str,
        label: str,
        recipients: QuerySet[User],
    ) -> None:
        """Send each recipient an in-app alert and an email."""
        contributor = contribution.user
        document = post.unified_document
        message = render_to_string(
            "email_activity_card.html",
            {
                "author": contributor.author_profile,
                "action": action,
                "amount": format_compact_usd(usd_amount),
                "created_date": contribution.created_date,
                "cover": build_work_cover(post),
            },
        )
        for recipient in recipients:
            self._notifications.try_send(
                notification_type,
                recipient=recipient,
                action_user=contributor,
                item=contribution,
                unified_document=document,
                extra={"amount": rsc_amount},
            )
            self._emails.send_message_email(
                [recipient.email],
                f"{contributor.full_name()} contributed to your {label}",
                message,
                link=document.frontend_view_link(),
                is_html=True,
            )

    @staticmethod
    def _rsc_receipt(purchase: Purchase) -> tuple[Decimal, Decimal, str]:
        """Return the contributed amount, the fee debited with it, and a format."""
        amount = Decimal(purchase.amount)
        debits = Balance.objects.filter(purchase=purchase).values_list(
            "amount", flat=True
        )
        fee = -sum(map(Decimal, debits)) - amount
        return amount.normalize(), fee.normalize(), "{:,f} RSC"

    def _send_receipt(
        self,
        contribution: Purchase | UsdFundraiseContribution,
        post: ResearchhubPost,
        target: str,
        amount: Decimal | float,
        fee: Decimal | float,
        money: str,
    ) -> None:
        """Email the contributor an exact receipt, regardless of email preferences.

        A receipt that cannot be built is logged so authors are still notified.
        """
        try:
            subject = f"Your {money.format(amount)} contribution to {target}"
            lines = [
                post.title,
                "",
                f"Amount: {money.format(amount)}",
                f"Fee: {money.format(fee)}",
                f"Total: {money.format(amount + fee)}",
                f"Date: {contribution.created_date:%Y-%m-%d}",
            ]
            self._emails.send_transactional_email(
                [contribution.user.email],
                subject,
                {
                    "subject": subject,
                    "body": "\n".join(lines),
                    "preserve_linebreaks": True,
                    "cta_url": post.unified_document.frontend_view_link(),
                },
                template="general_branded_email",
            )
        except Exception:
            logger.exception("Contribution receipt failed for %s", contribution.id)
