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

    def test_notify_requested_emails_user_with_withdrawal_details(self) -> None:
        """Send a transactional email describing the requested withdrawal."""
        # Act
        self.service.notify_requested(self.withdrawal.id)

        # Assert
        self.email_service.send_transactional_email.assert_called_once()
        call = self.email_service.send_transactional_email.call_args
        self.assertEqual(call.args[0], [self.user.email])
        self.assertEqual(call.args[1], "Your withdrawal of 1,500.5 RSC is on its way")
        self.assertEqual(call.kwargs["template"], "general_branded_email")
        body = call.args[2]["body"]
        for detail in ("1,500.5 RSC", "Fee: 10 RSC", "Network: Base", "To: 0xto"):
            self.assertIn(detail, body)
        self.assertIn("If you did not request this withdrawal", body)
        self.assertNotIn("Transaction:", body)

    def test_notify_completed_emails_user_with_transaction_hash(self) -> None:
        """Send a transactional email once the withdrawal is confirmed."""
        # Arrange
        self.withdrawal.transaction_hash = "0xhash"
        self.withdrawal.save()

        # Act
        self.service.notify_completed(self.withdrawal.id)

        # Assert
        self.email_service.send_transactional_email.assert_called_once()
        call = self.email_service.send_transactional_email.call_args
        self.assertEqual(call.args[0], [self.user.email])
        self.assertEqual(call.args[1], "Your withdrawal of 1,500.5 RSC is complete")
        self.assertIn("Transaction: 0xhash", call.args[2]["body"])

    def test_no_email_when_withdrawal_has_no_user(self) -> None:
        """Skip the email when the withdrawal's user was deleted."""
        # Arrange
        self.withdrawal.user = None
        self.withdrawal.save()

        # Act
        self.service.notify_requested(self.withdrawal.id)

        # Assert
        self.email_service.send_transactional_email.assert_not_called()
