import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from purchase.models import Balance, RscExchangeRate
from researchhub_document.services.work_cover_service_for_email import (
    format_compact_usd,
)
from user.models import User

logger = logging.getLogger(__name__)

EMAIL_CLAIM_TIMEOUT = timedelta(hours=1)


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

    def send_reminders(self, *, send_email: bool = False) -> int:
        """Create one alert per half-month and optionally attempt its monthly email."""
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
        # Email-enabled reruns retain the month's first reminder after the 15th.
        period_day = 1 if send_email or now.day < 15 else 15
        period_start = now.replace(
            day=period_day, hour=0, minute=0, second=0, microsecond=0
        )

        sent_count = 0
        for user in candidates.iterator():
            try:
                funding_credits = user.get_funding_credits_balance()
                if funding_credits <= 0:
                    continue

                reminder, created = self._get_reminder(
                    user, funding_credits, period_start
                )
                sent_count += int(created)
                if not send_email or reminder.extra["email_state"] == "sent":
                    continue
                email = self._build_email(funding_credits)
                if email is not None:
                    self._email_reminder(user, reminder, *email)
            except Exception:
                logger.exception(
                    "Error sending funding credits reminder for user %s", user.id
                )

        logger.info("Created %d funding credits reminders", sent_count)
        return sent_count

    def _get_reminder(
        self, user: User, funding_credits: Decimal, period_start: datetime
    ) -> tuple[Notification, bool]:
        """Create a period's alert once, adopting an existing legacy alert if needed."""
        period = period_start.date().isoformat()
        reminders = Notification.objects.filter(
            notification_type=Notification.FUNDING_CREDITS_REMINDER,
            recipient=user,
        )
        try:
            with transaction.atomic():
                reminder = reminders.filter(extra__reminder_period=period).first()
                if reminder is not None:
                    return reminder, False

                if period_start.day == 1:
                    period_end = period_start.replace(day=15)
                else:
                    period_end = period_start.replace(day=1)
                    if period_end.month == 12:
                        period_end = period_end.replace(
                            year=period_end.year + 1, month=1
                        )
                    else:
                        period_end = period_end.replace(month=period_end.month + 1)
                reminder = (
                    reminders.filter(
                        created_date__gte=period_start, created_date__lt=period_end
                    )
                    .exclude(extra__has_key="reminder_period")
                    .first()
                )
                if reminder is not None:
                    reminders.filter(pk=reminder.pk).exclude(
                        extra__has_key="reminder_period"
                    ).update(
                        extra={
                            **reminder.extra,
                            "reminder_period": period,
                            "email_state": "pending",
                        }
                    )
                    reminder.refresh_from_db(fields=["extra"])
                    return reminder, False

                reminder = self._notifications.send(
                    Notification.FUNDING_CREDITS_REMINDER,
                    recipient=user,
                    action_user=user,
                    item=user,
                    extra={
                        "amount": str(funding_credits),
                        "reminder_period": period,
                        "email_state": "pending",
                    },
                )
                return reminder, True
        except IntegrityError:
            reminder = reminders.filter(extra__reminder_period=period).first()
            if reminder is None:
                raise
            return reminder, False

    def _build_email(self, funding_credits: Decimal) -> tuple[str, str] | None:
        """Render a funding-only reminder when the credits are worth at least $1."""
        funding_credits_usd = float(funding_credits) * RscExchangeRate.get_latest()
        if funding_credits_usd < 1:
            return None
        amount = format_compact_usd(funding_credits_usd)
        message = render_to_string(
            "email_funding_credits_card.html",
            {"assets_base_url": settings.ASSETS_BASE_URL},
        )
        return f"You have {amount} in unused funding credits", message

    def _email_reminder(
        self, user: User, reminder: Notification, subject: str, message: str
    ) -> None:
        """Claim email outside a transaction and recover abandoned hourly claims."""
        now = timezone.now()
        claimed_extra = {
            **reminder.extra,
            "email_state": "sending",
            "email_claimed_at": now.isoformat(),
            "email_claim_token": uuid4().hex,
        }
        reminders = Notification.objects.filter(pk=reminder.pk)
        if not reminders.filter(
            Q(extra__email_state="pending")
            | Q(
                extra__email_state="sending",
                extra__email_claimed_at__lt=(now - EMAIL_CLAIM_TIMEOUT).isoformat(),
            )
        ).update(extra=claimed_extra):
            return

        # Expired claims can be retried after a crash; SES delivery is at-least-once.
        owned_claim = reminders.filter(
            extra__email_state="sending",
            extra__email_claim_token=claimed_extra["email_claim_token"],
        )
        try:
            self._emails.send_email(
                [user.email],
                subject,
                {
                    "subject": subject,
                    "body": mark_safe(message),
                    "cta_url": f"{settings.BASE_FRONTEND_URL}/fund/proposals",
                    "cta_label": "Fund Science \u2192",
                },
                template="general_branded_email",
                raise_on_error=True,
            )
        except Exception:
            owned_claim.update(extra={**claimed_extra, "email_state": "pending"})
            raise
        owned_claim.update(extra={**claimed_extra, "email_state": "sent"})
