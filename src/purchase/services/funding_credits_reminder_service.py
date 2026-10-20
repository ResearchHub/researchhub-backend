import logging

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

MIN_EMAIL_USD = 1


class FundingCreditsReminderService:
    """Remind users to put their unused funding credits toward research."""

    def __init__(
        self,
        notification_service: NotificationService | None = None,
        email_service: EmailService | None = None,
    ) -> None:
        """Configure notification and email delivery for reminders."""
        self._notifications = notification_service or NotificationService()
        self._emails = email_service or EmailService()

    def send_reminders(self) -> dict[str, int]:
        """Notify holders once per half-month, also emailing in the first half."""
        now = timezone.now()
        is_first_half = now.day < 15
        period_start = now.replace(
            day=1 if is_first_half else 15, hour=0, minute=0, second=0, microsecond=0
        )
        rsc_usd_rate = RscExchangeRate.get_latest()
        message = render_to_string(
            "email_funding_credits_card.html",
            {"assets_base_url": settings.ASSETS_BASE_URL},
        )
        candidate_user_ids = Balance.objects.filter(
            is_locked=True, lock_type=Balance.LockType.FUNDING_CREDIT
        ).values_list("user_id", flat=True)
        candidates = User.objects.filter(
            id__in=candidate_user_ids,
            is_active=True,
            is_suspended=False,
            probable_spammer=False,
        )

        sent_count = 0
        for user in candidates.iterator():
            try:
                funding_credits = user.get_funding_credits_balance()
                if funding_credits <= 0:
                    continue

                if not self._notifications.send_once(
                    Notification.FUNDING_CREDITS_REMINDER,
                    recipient=user,
                    action_user=user,
                    item=user,
                    extra={"amount": str(funding_credits)},
                    since=period_start,
                ):
                    continue
                sent_count += 1

                funding_credits_usd = float(funding_credits) * rsc_usd_rate
                if is_first_half and funding_credits_usd >= MIN_EMAIL_USD:
                    self._send_reminder_email(user, funding_credits_usd, message)
            except Exception:
                logger.exception(
                    "Error sending funding credits reminder for user %s", user.id
                )

        logger.info("Sent %d funding credits reminders", sent_count)
        return {"sent_count": sent_count}

    def _send_reminder_email(
        self, user: User, funding_credits_usd: float, message: str
    ) -> None:
        """Email the user how much their unused funding credits are worth."""
        amount = format_compact_usd(funding_credits_usd)
        self._emails.send_message_email(
            [user.email],
            f"You have {amount} in unused funding credits",
            message,
            link=f"{settings.BASE_FRONTEND_URL}/fund/proposals",
            cta_label="Fund Science →",
            is_html=True,
        )
