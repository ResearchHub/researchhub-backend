import logging
from decimal import Decimal

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import Balance, RscExchangeRate
from researchhub_document.services.work_cover_service_for_email import (
    format_compact_usd,
)
from user.models import User

logger = logging.getLogger(__name__)


class FundingCreditsReminderService:
    """Remind users who still hold unspent funding credits to spend them."""

    def __init__(
        self,
        notification_service: NotificationService | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        """Configure notification and email delivery for reminders."""
        self._notifications = notification_service or NotificationService()
        self._emails = email_service or EmailService()

    def send_reminders(self) -> int:
        """Alert each user holding spendable credits, also emailing them on the 1st.

        Returns the number of users alerted.
        """
        # Prefilter to users who have at least one locked, spendable balance row.
        # The effective balance is confirmed per-user below, since debits can zero
        # it out even when credit rows exist.
        candidate_user_ids = (
            Balance.objects.filter(
                is_locked=True, lock_type__in=Balance.LOCKED_SPEND_ORDER
            )
            .values_list("user_id", flat=True)
            .distinct()
        )
        candidates = User.objects.filter(id__in=candidate_user_ids).select_related(
            "author_profile"
        )
        now = timezone.now()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        sent_count = 0
        for user in candidates.iterator():
            locked_balances = user.get_locked_balance_by_lock_type()
            spendable = sum(locked_balances.values(), Decimal(0))
            if spendable <= 0:
                continue

            try:
                if self._notifications.send_once(
                    Notification.FUNDING_CREDITS_REMINDER,
                    recipient=user,
                    action_user=user,
                    item=user,
                    extra={"amount": str(spendable)},
                    since=start_of_today,
                ):
                    if now.day == 1:
                        self._email_reminder(user, spendable, locked_balances)
                    sent_count += 1
            except Exception:
                logger.exception(
                    "Error sending funding credits reminder for user %s", user.id
                )

        logger.info("Sent %d funding credits reminders", sent_count)
        return sent_count

    def _email_reminder(
        self, user: User, spendable: Decimal, locked_balances: dict[str, Decimal]
    ) -> None:
        """Email the user a snapshot of their wallet, mirroring /researchcoin."""
        rate = RscExchangeRate.get_latest()
        funding_credits = locked_balances.get(
            Balance.LockType.FUNDING_CREDIT, Decimal(0)
        )
        researchcoin = user.get_balance() + locked_balances.get(
            Balance.LockType.PROMOTIONAL, Decimal(0)
        )
        total = researchcoin + funding_credits
        amount = format_compact_usd(float(spendable) * rate)
        message = render_to_string(
            "email_funding_credits_card.html",
            {
                "author": user.author_profile,
                "action": "Has",
                "amount": amount,
                "action_trailing": "in funding credits",
                "created_date": timezone.now(),
                "total_rsc": total,
                "total_usd": float(total) * rate,
                "assets": [
                    _build_wallet_row(
                        "ResearchCoin", "ResearchCoin.png", researchcoin, rate
                    ),
                    _build_wallet_row(
                        "Funding Credits", "FundingCredits.png", funding_credits, rate
                    ),
                ],
            },
        )
        self._emails.send_message_email(
            [user.email],
            f"You have {amount} in unused funding credits",
            message,
            link=f"{settings.BASE_FRONTEND_URL}/researchcoin",
            is_html=True,
        )


def _build_wallet_row(name: str, icon: str, rsc: Decimal, rate: float) -> dict:
    """Describe one wallet asset row with its icon, RSC balance and USD value."""
    return {
        "name": name,
        "icon_url": f"{settings.ASSETS_BASE_URL}/email_assets/{icon}",
        "rsc": rsc,
        "usd": float(rsc) * rate,
    }
