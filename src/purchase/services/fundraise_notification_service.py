from django.db.models import Q, QuerySet
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import Purchase, RscExchangeRate, UsdFundraiseContribution
from purchase.related_models.constants.currency import USD
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.services.work_cover_service_for_email import (
    build_work_cover,
    format_compact_usd,
)
from user.models import User


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
            receipt_target = "a proposal"
        else:
            contribution = Purchase.objects.select_related(
                "user__author_profile", "funding_distribution"
            ).get(id=contribution_id)
            fundraise = contribution.item
            rsc_amount = contribution.amount
            usd_amount = float(rsc_amount) * contribution.rsc_usd_rate
            # A pool distribution moves pool funds, not the distributor's own.
            receipt_target = (
                None if hasattr(contribution, "funding_distribution") else "a proposal"
            )

        proposal = fundraise.unified_document.get_document()
        self._notify_recipients(
            Notification.FUNDRAISE_CONTRIBUTION,
            contribution,
            rsc_amount,
            usd_amount,
            proposal,
            action="Funded a proposal",
            label="proposal",
            receipt_target=receipt_target,
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

        self._notify_recipients(
            Notification.FUNDING_POOL_CONTRIBUTION,
            purchase,
            purchase.amount,
            float(purchase.amount) * purchase.rsc_usd_rate,
            grant.unified_document.get_document(),
            action="Added to an RFP’s funding pool",
            label="RFP",
            receipt_target="an RFP",
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
        receipt_target: str | None,
        recipients: QuerySet[User],
    ) -> None:
        """Alert and email each recipient, then email the contributor a receipt."""
        contributor = contribution.user
        document = post.unified_document
        link = document.frontend_view_link()
        amount = format_compact_usd(usd_amount)
        message = render_to_string(
            "email_activity_card.html",
            {
                "author": contributor.author_profile,
                "action": action,
                "amount": amount,
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
                link=link,
                is_html=True,
            )
        if receipt_target:
            subject = f"You contributed {amount} to {receipt_target}"
            self._emails.send_transactional_email(
                [contributor.email],
                subject,
                {"subject": subject, "body": mark_safe(message), "cta_url": link},
                template="general_branded_email",
            )
