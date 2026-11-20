from unittest.mock import Mock

from django.test import TestCase

from mailing_list.services import EmailService
from reputation.models import Withdrawal
from reputation.related_models.paid_status_mixin import PaidStatusModelMixin
from reputation.services.withdrawal_notification_service import (
    WithdrawalNotificationService,
)
from user.tests.helpers import create_random_default_user


class WithdrawalNotificationServiceTests(TestCase):
    """Verify users are emailed about their withdrawals."""

    def setUp(self) -> None:
        """Create a withdrawal and inject a mocked email service."""
        self.user = create_random_default_user("withdrawal_email_user")
        self.email_service = Mock(spec=EmailService)
        self.service = WithdrawalNotificationService(email_service=self.email_service)
        self.withdrawal = Withdrawal.objects.create(
            user=self.user,
            token_address="0xtoken",
            from_address="0xfrom",
            to_address="0xto",
            amount="1500.50",
            fee="10",
            network="BASE",
            paid_status=PaidStatusModelMixin.INITIATED,
        )

    def _sent_email(self) -> tuple[list[str], str, str]:
        """Return the recipients, subject and body of the one email sent."""
        self.email_service.send_transactional_email.assert_called_once()
        call = self.email_service.send_transactional_email.call_args
        return call.args[0], call.args[1], call.args[2]["body"]

    def test_requested_email_describes_withdrawal_and_warns(self) -> None:
        """Email the amounts and destination when a withdrawal is requested."""
        # Act
        self.service.notify(self.withdrawal.id, PaidStatusModelMixin.INITIATED)

        # Assert
        recipients, subject, body = self._sent_email()
        self.assertEqual(recipients, [self.user.email])
        self.assertEqual(subject, "Your withdrawal of 1,500.5 RSC is on its way")
        for detail in (
            f"Withdrawal: #{self.withdrawal.id}",
            "Amount sent: 1,500.5 RSC",
            "Fee: 10 RSC",
            "Total: 1,510.5 RSC",
            "Network: Base",
            "To: 0xto",
            "If you did not request this withdrawal",
        ):
            self.assertIn(detail, body)
        self.assertNotIn("Transaction:", body)

    def test_completed_email_includes_transaction_hash(self) -> None:
        """Email the transaction hash once the withdrawal is confirmed."""
        # Arrange
        self.withdrawal.transaction_hash = "0xhash"
        self.withdrawal.save()

        # Act
        self.service.notify(self.withdrawal.id, PaidStatusModelMixin.PAID)

        # Assert
        _, subject, body = self._sent_email()
        self.assertEqual(subject, "Your withdrawal of 1,500.5 RSC is complete")
        self.assertIn("Transaction: 0xhash", body)

    def test_failed_email_says_funds_were_returned(self) -> None:
        """Tell the user when a withdrawal fails."""
        # Act
        self.service.notify(self.withdrawal.id, PaidStatusModelMixin.FAILED)

        # Assert
        _, subject, body = self._sent_email()
        self.assertEqual(subject, "Your withdrawal of 1,500.5 RSC failed")
        self.assertIn("your RSC has been returned", body)

    def test_no_email_when_withdrawal_has_no_user(self) -> None:
        """Skip the email when the withdrawal's user was deleted."""
        # Arrange
        self.withdrawal.user = None
        self.withdrawal.save()

        # Act
        self.service.notify(self.withdrawal.id, PaidStatusModelMixin.INITIATED)

        # Assert
        self.email_service.send_transactional_email.assert_not_called()
