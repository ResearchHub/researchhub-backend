from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import ANY, Mock, patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from mailing_list.services import EmailService
from notification.models import Notification
from purchase.models import Balance, RscExchangeRate
from purchase.related_models.constants.currency import USD
from purchase.services.funding_credits_reminder_service import (
    FundingCreditsReminderService,
)
from user.models import User
from user.tests.helpers import create_random_default_user


class FundingCreditsReminderServiceTests(TestCase):
    def setUp(self) -> None:
        """Freeze the clock on the 1st and inject a mocked email service."""
        self.now = self.enterContext(
            patch(
                "django.utils.timezone.now",
                return_value=datetime(2026, 11, 1, 16, tzinfo=UTC),
            )
        )
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, target_currency=USD)
        self.user = create_random_default_user("funding_credits_reminder")
        self.notifications = Notification.objects.filter(
            notification_type=Notification.FUNDING_CREDITS_REMINDER,
            recipient=self.user,
        )
        self.email_service = Mock(spec=EmailService)
        self.service = FundingCreditsReminderService(email_service=self.email_service)

    def _add_funding_credits(self, amount: Decimal) -> None:
        """Add a funding-credit ledger entry for the user."""
        Balance.objects.create(
            user=self.user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.user.id,
            amount=str(amount),
            is_locked=True,
            lock_type=Balance.LockType.FUNDING_CREDIT,
        )

    def test_notifies_and_emails_funding_credit_holders(self) -> None:
        """A holder gets an alert and an email on the 1st of the month."""
        # Arrange
        self._add_funding_credits(Decimal(50))

        # Act
        result = self.service.send_reminders()

        # Assert
        self.assertEqual(result, {"sent_count": 1})
        amount = self.notifications.get().extra["amount"]
        self.assertEqual(Decimal(amount), Decimal(50))
        self.email_service.send_message_email.assert_called_once_with(
            [self.user.email],
            "You have $25 in unused funding credits",
            ANY,
            link=f"{settings.BASE_FRONTEND_URL}/fund/proposals",
            cta_label="Fund Science →",
            is_html=True,
        )

    def test_skips_users_without_funding_credits(self) -> None:
        """A user with no funding credits gets no reminder."""
        # Act
        result = self.service.send_reminders()

        # Assert
        self.assertEqual(result, {"sent_count": 0})
        self.assertFalse(self.notifications.exists())

    def test_skips_users_whose_credits_are_spent(self) -> None:
        """Credits fully offset by a debit do not trigger a reminder."""
        # Arrange
        self._add_funding_credits(Decimal(40))
        self._add_funding_credits(Decimal(-40))

        # Act
        result = self.service.send_reminders()

        # Assert
        self.assertEqual(result, {"sent_count": 0})
        self.assertFalse(self.notifications.exists())

    def test_sends_once_per_half_month(self) -> None:
        """A second run in the same half-month neither alerts nor emails again."""
        # Arrange
        self._add_funding_credits(Decimal(50))
        self.service.send_reminders()
        self.email_service.reset_mock()
        self.now.return_value = datetime(2026, 11, 3, 16, tzinfo=UTC)

        # Act
        result = self.service.send_reminders()

        # Assert
        self.assertEqual(result, {"sent_count": 0})
        self.assertEqual(self.notifications.count(), 1)
        self.email_service.send_message_email.assert_not_called()

    def test_notifies_without_emailing_in_the_second_half(self) -> None:
        """The mid-month run alerts holders again but leaves email to the 1st."""
        # Arrange
        self._add_funding_credits(Decimal(50))
        self.service.send_reminders()
        self.email_service.reset_mock()
        self.now.return_value = datetime(2026, 11, 15, 16, tzinfo=UTC)

        # Act
        result = self.service.send_reminders()

        # Assert
        self.assertEqual(result, {"sent_count": 1})
        self.assertEqual(self.notifications.count(), 2)
        self.email_service.send_message_email.assert_not_called()

    def test_skips_email_for_credits_under_one_dollar(self) -> None:
        """Credits worth under $1 still get an alert but no email."""
        # Arrange
        self._add_funding_credits(Decimal("1.99"))

        # Act
        result = self.service.send_reminders()

        # Assert
        self.assertEqual(result, {"sent_count": 1})
        self.email_service.send_message_email.assert_not_called()
