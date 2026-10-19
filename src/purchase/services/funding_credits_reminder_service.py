import logging
from datetime import datetime
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
    """Remind eligible users to put their unused funding credits toward research."""

    def __init__(
        self,
        notification_service: NotificationService | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        """Configure notification and email delivery for reminders."""
        self._notifications = notification_service or NotificationService()
        self._emails = email_service or EmailService()

    def send_reminders(self, *, send_email: bool = False) -> dict[str, int]:
        """Notify holders once per half-month and optionally email once a month."""
        candidate_user_ids = Balance.objects.filter(
            is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        ).values_list("user_id", flat=True)
        candidates = User.objects.filter(
            id__in=candidate_user_ids,
            is_active=True,
            is_suspended=False,
            probable_spammer=False,
        )
        now = timezone.now()
        period_start = now.replace(
            day=1 if now.day < 15 else 15, hour=0, minute=0, second=0, microsecond=0
        )
        month_start = period_start.replace(day=1)
        message = render_to_string(
            "email_funding_credits_card.html",
            {"assets_base_url": settings.ASSETS_BASE_URL},
        )

        notification_count = 0
        email_count = 0
        for user in candidates.iterator():
            try:
                funding_credits = user.get_funding_credits_balance()
                if funding_credits <= 0:
                    continue

                if self._notifications.send_once(
                    Notification.FUNDING_CREDITS_REMINDER,
                    recipient=user,
                    action_user=user,
                    item=user,
                    extra={"amount": str(funding_credits)},
                    since=period_start,
                ):
                    notification_count += 1
                if send_email and self._email_reminder(
                    user, funding_credits, message, month_start
                ):
                    email_count += 1
            except Exception:
                logger.exception(
                    "Error sending funding credits reminder for user %s", user.id
                )

        logger.info(
            "Sent %d funding credits notifications and %d emails",
            notification_count,
            email_count,
        )
        return {"notification_count": notification_count, "email_count": email_count}

    def _email_reminder(
        self,
        user: User,
        funding_credits: Decimal,
        message: str,
        month_start: datetime,
    ) -> bool:
        """Email credits worth at least $1, at most once per calendar month."""
        sent_date = user.funding_credits_email_sent_date
        if sent_date is not None and sent_date >= month_start:
            return False
        funding_credits_usd = RscExchangeRate.rsc_to_usd(float(funding_credits))
        if funding_credits_usd < 1:
            return False

        amount = format_compact_usd(funding_credits_usd)
        accepted = self._emails.send_message_email(
            [user.email],
            f"You have {amount} in unused funding credits",
            message,
            link=f"{settings.BASE_FRONTEND_URL}/fund/proposals",
            cta_label="Fund Science \u2192",
            is_html=True,
        )
        if not accepted:
            return False
        User.objects.filter(pk=user.pk).update(
            funding_credits_email_sent_date=timezone.now()
        )
        return True
