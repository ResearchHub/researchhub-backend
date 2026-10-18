from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from mailing_list.services import EmailService
from notification.models import Notification
from purchase.circle.client import CircleTransferError
from purchase.models import Balance, Fundraise, RscExchangeRate, Wallet
from purchase.related_models.constants.currency import USD
from purchase.services.fundraise_service import FundraiseService
from purchase.tasks import (
    complete_eligible_fundraises,
    send_funding_credits_reminders,
    send_monthly_preregistration_update_reminders,
    sweep_deposit_to_multisig,
)
from reputation.related_models.deposit import Deposit
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user, create_user

User = get_user_model()


class FundraiseTasksTest(TestCase):
    def setUp(self):
        cache.clear()

        # Create a moderator user
        self.user = create_random_authenticated_user("fundraise_tasks", moderator=True)

        # Create a post
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Set up service
        self.fundraise_service = FundraiseService()

        # Create required exchange rate for USD to RSC conversion
        self.rsc_exchange_rate = RscExchangeRate.objects.create(
            rate=0.5,  # 1 USD = 2 RSC
            real_rate=0.5,
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        self.exchange_rate_patcher = patch(
            "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest",
            return_value=self.rsc_exchange_rate.rate,
        )
        self.exchange_rate_patcher.start()
        self.addCleanup(self.exchange_rate_patcher.stop)

        # Create required bounty fee for fee calculations
        from reputation.models import BountyFee

        self.bounty_fee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

        # Create bank user that's needed for fee calculations
        self.bank_user = create_user(email="bank@researchhub.com")

    def test_complete_eligible_fundraises_success(self):
        """Test that eligible fundraises are automatically completed"""
        # Create a fundraise that's more than a week old
        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Manually set the start_date to be more than a week old
        old_date = datetime.now(UTC) - timedelta(days=8)
        fundraise.start_date = old_date
        fundraise.save()

        # Add funds to escrow to simulate reaching the goal
        # Goal is $100 USD, with rate 0.5 that means we need 200 RSC
        fundraise.escrow.amount_holding = Decimal("200.00")  # More than goal of $100
        fundraise.escrow.save()

        # Verify initial state
        self.assertEqual(fundraise.status, Fundraise.OPEN)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("200.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("0.00"))

        # Run the task
        result = complete_eligible_fundraises()

        # Verify the task processed the fundraise
        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["error_count"], 0)

        # Verify the fundraise was completed
        fundraise.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.COMPLETED)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("0.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("200.00"))

    def test_complete_eligible_fundraises_goal_not_met(self):
        """Test that fundraises that haven't met their goal are not completed"""
        # Create a fundraise that's more than a week old
        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Manually set the start_date to be more than a week old
        old_date = datetime.now(UTC) - timedelta(days=8)
        fundraise.start_date = old_date
        fundraise.save()

        # Add insufficient funds to escrow (less than goal)
        # Goal is $100 USD, with rate 0.5 that means we need 200 RSC for goal
        fundraise.escrow.amount_holding = Decimal("100.00")  # Only 100 RSC = $50 USD
        fundraise.escrow.save()

        # Verify initial state
        self.assertEqual(fundraise.status, Fundraise.OPEN)

        # Run the task
        result = complete_eligible_fundraises()

        # Verify the task did not process the fundraise
        self.assertEqual(result["completed_count"], 0)
        self.assertEqual(result["error_count"], 0)

        # Verify the fundraise remains open
        fundraise.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.OPEN)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("100.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("0.00"))

    def test_complete_eligible_fundraises_too_new(self):
        """Test that fundraises less than a week old are not completed"""
        # Create a recent fundraise
        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Add funds to escrow to simulate reaching the goal
        fundraise.escrow.amount_holding = Decimal("200.00")  # More than goal of $100
        fundraise.escrow.save()

        # Verify initial state
        self.assertEqual(fundraise.status, Fundraise.OPEN)

        # Run the task
        result = complete_eligible_fundraises()

        # Verify the task did not process the fundraise (too new)
        self.assertEqual(result["completed_count"], 0)
        self.assertEqual(result["error_count"], 0)

        # Verify the fundraise remains open
        fundraise.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.OPEN)
        self.assertEqual(fundraise.escrow.amount_holding, Decimal("200.00"))
        self.assertEqual(fundraise.escrow.amount_paid, Decimal("0.00"))


class SweepDepositTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sweepuser")
        self.wallet = Wallet.objects.create(
            user=self.user,
            circle_wallet_id="wallet-1",
            circle_base_wallet_id="wallet-1-base",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
            address="0xSweepAddress",
        )
        self.deposit = Deposit.objects.create(
            user=self.user,
            amount="100",
            network="BASE",
            from_address="",
            circle_transaction_id="notif-1",
            sweep_status=Deposit.SWEEP_PENDING,
        )

    @patch("purchase.tasks.CircleWalletService")
    def test_sweep_task_calls_execute_sweep(self, mock_service_class):
        sweep_deposit_to_multisig.run("wallet-1", "100", "BASE", "notif-1")

        mock_service_class.return_value.execute_sweep.assert_called_once_with(
            circle_wallet_id="wallet-1",
            amount="100",
            network="BASE",
            sweep_reference="notif-1",
        )

    @patch.object(sweep_deposit_to_multisig, "retry", side_effect=RuntimeError("retry"))
    @patch("purchase.tasks.CircleWalletService")
    def test_sweep_task_retries_on_transfer_error(self, mock_service_class, mock_retry):
        mock_service_class.return_value.execute_sweep.side_effect = CircleTransferError(
            "circle failed"
        )

        with self.assertRaises(RuntimeError):
            sweep_deposit_to_multisig.run("wallet-1", "100", "BASE", "notif-1")

        mock_retry.assert_called_once()

    @patch.object(sweep_deposit_to_multisig, "retry", side_effect=RuntimeError("retry"))
    @patch("purchase.tasks.CircleWalletService")
    def test_sweep_task_retries_on_unexpected_error(
        self, mock_service_class, mock_retry
    ):
        mock_service_class.return_value.execute_sweep.side_effect = RuntimeError(
            "transport failed"
        )

        with self.assertRaises(RuntimeError):
            sweep_deposit_to_multisig.run("wallet-1", "100", "BASE", "notif-1")

        mock_retry.assert_called_once()


class PreregistrationUpdateReminderTest(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("reminder_test", moderator=True)
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        self.future = datetime.now(UTC) + timedelta(days=30)
        self.notif_qs = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE_REMINDER,
            recipient=self.user,
        )

    def _create_fundraise(self, status=Fundraise.OPEN, end_date=None):
        f = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=status,
        )
        if end_date is not None:
            Fundraise.objects.filter(id=f.id).update(end_date=end_date)
        return f

    def test_sends_for_completed_preregistration(self):
        # Arrange
        self._create_fundraise(status=Fundraise.COMPLETED)
        # Act
        result = send_monthly_preregistration_update_reminders()
        # Assert
        self.assertEqual(result["sent_count"], 1)
        self.assertTrue(self.notif_qs.exists())

    def test_skips_open_and_closed(self):
        # Arrange
        self._create_fundraise(status=Fundraise.OPEN)
        self._create_fundraise(status=Fundraise.CLOSED)
        # Act
        result = send_monthly_preregistration_update_reminders()
        # Assert
        self.assertEqual(result["sent_count"], 0)

    def test_deduplicates_within_same_month(self):
        # Arrange
        self._create_fundraise(status=Fundraise.COMPLETED)
        send_monthly_preregistration_update_reminders()
        # Act
        result = send_monthly_preregistration_update_reminders()
        # Assert
        self.assertEqual(result["sent_count"], 0)
        self.assertEqual(self.notif_qs.count(), 1)

    def test_multiple_completed_fundraises_sends_one_reminder(self):
        # Arrange
        self._create_fundraise(status=Fundraise.COMPLETED)
        self._create_fundraise(status=Fundraise.COMPLETED)
        self._create_fundraise(status=Fundraise.COMPLETED)
        # Act
        result = send_monthly_preregistration_update_reminders()
        # Assert
        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(self.notif_qs.count(), 1)


class FundingCreditsReminderTest(TestCase):
    def setUp(self) -> None:
        """Create an eligible account and a fixed reminder period."""
        self.user = create_random_authenticated_user("funding_credits_reminder")
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, target_currency=USD)
        self.notif_qs = Notification.objects.filter(
            notification_type=Notification.FUNDING_CREDITS_REMINDER,
            recipient=self.user,
        )
        self.clock = patch.object(
            timezone, "now", return_value=datetime(2026, 11, 1, tzinfo=UTC)
        )
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)

    def _add_funding_credit(
        self, user: User, amount: Decimal, lock_type: str | None = None
    ) -> Balance:
        """Add a locked ledger entry for the requested credit category."""
        return Balance.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(User),
            object_id=user.id,
            amount=str(amount),
            is_locked=True,
            lock_type=lock_type or Balance.LockType.FUNDING_CREDIT,
        )

    def test_sends_funding_credits_email(self) -> None:
        """Describe only funding credits and link directly to proposals."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(50))
        self._add_funding_credit(
            self.user, Decimal(60), lock_type=Balance.LockType.PROMOTIONAL
        )
        # Act
        result = send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(self.notif_qs.count(), 1)
        self.assertEqual(self.notif_qs.get().extra["amount"], "50")
        self.assertEqual(self.notif_qs.get().extra["email_state"], "sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("$25 in unused funding credits", mail.outbox[0].subject)
        self.assertIn("/fund/proposals", mail.outbox[0].alternatives[0].content)
        self.assertIn("Fund Science", mail.outbox[0].alternatives[0].content)

    def test_emails_an_existing_notification(self) -> None:
        """Allow an email-enabled rerun after a notification-only run."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(50))
        send_funding_credits_reminders()
        notification_only_email_count = len(mail.outbox)
        # Act
        result = send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(result["sent_count"], 0)
        self.assertEqual(notification_only_email_count, 0)
        self.assertEqual(self.notif_qs.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_preserves_notification_when_email_cannot_be_built(self) -> None:
        """Leave the recipient eligible for retry when exchange-rate lookup fails."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(50))
        # Act
        with patch.object(RscExchangeRate, "get_latest", side_effect=RuntimeError):
            result = send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(self.notif_qs.count(), 1)
        self.assertEqual(self.notif_qs.get().extra["email_state"], "pending")
        self.assertEqual(len(mail.outbox), 0)

    def test_retries_failed_email_on_the_next_day(self) -> None:
        """Retry a real delivery failure without duplicating the in-app alert."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(50))
        # Act
        with patch.object(EmailService, "_send_message", side_effect=RuntimeError):
            first_result = send_funding_credits_reminders(send_email=True)
        failed_state = self.notif_qs.get().extra["email_state"]
        self.now.return_value = datetime(2026, 11, 2, tzinfo=UTC)
        retry_result = send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(first_result["sent_count"], 1)
        self.assertEqual(failed_state, "pending")
        self.assertEqual(retry_result["sent_count"], 0)
        self.assertEqual(self.notif_qs.count(), 1)
        self.assertEqual(self.notif_qs.get().extra["email_state"], "sent")
        self.assertEqual(len(mail.outbox), 1)

    def test_skips_reminders_without_funding_credits(self) -> None:
        """Ignore an account whose only spendable balance is promotional."""
        # Arrange
        self._add_funding_credit(
            self.user, Decimal(60), lock_type=Balance.LockType.PROMOTIONAL
        )
        # Act
        result = send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(result["sent_count"], 0)
        self.assertFalse(self.notif_qs.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_skips_reminders_when_credits_are_spent(self) -> None:
        """Ignore funding credits canceled by an equal debit."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(40))
        self._add_funding_credit(self.user, Decimal(-40))
        # Act
        result = send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(result["sent_count"], 0)
        self.assertFalse(self.notif_qs.exists())

    def test_deduplicates_next_day_and_late_monthly_reruns(self) -> None:
        """Keep one monthly email when the first run is retried on later days."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(25))
        send_funding_credits_reminders(send_email=True)
        # Act
        self.now.return_value = datetime(2026, 11, 2, tzinfo=UTC)
        next_day_result = send_funding_credits_reminders(send_email=True)
        self.now.return_value = datetime(2026, 11, 16, tzinfo=UTC)
        late_result = send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(next_day_result["sent_count"], 0)
        self.assertEqual(late_result["sent_count"], 0)
        self.assertEqual(self.notif_qs.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_notifies_again_in_the_next_period(self) -> None:
        """Create the midmonth alert without sending a second monthly email."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(25))
        send_funding_credits_reminders(send_email=True)
        # Act
        self.now.return_value = datetime(2026, 11, 15, tzinfo=UTC)
        result = send_funding_credits_reminders()
        # Assert
        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(self.notif_qs.count(), 2)
        self.assertEqual(len(mail.outbox), 1)

    def test_emails_only_credits_worth_at_least_one_dollar(self) -> None:
        """Notify small balances while reserving email for balances worth $1."""
        # Arrange
        self._add_funding_credit(self.user, Decimal("1.99"))
        # Act
        send_funding_credits_reminders(send_email=True)
        small_balance_email_count = len(mail.outbox)
        self._add_funding_credit(self.user, Decimal("0.01"))
        send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(small_balance_email_count, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.notif_qs.count(), 1)
        self.assertIn("$1 in unused funding credits", mail.outbox[0].subject)

    def test_skips_ineligible_accounts(self) -> None:
        """Exclude inactive, suspended and probable-spammer recipients."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(50))
        # Act
        results = []
        for flags in (
            {"is_active": False},
            {"is_suspended": True},
            {"probable_spammer": True},
        ):
            User.objects.filter(pk=self.user.pk).update(
                is_active=True, is_suspended=False, probable_spammer=False
            )
            User.objects.filter(pk=self.user.pk).update(**flags)
            results.append(send_funding_credits_reminders(send_email=True))
        # Assert
        self.assertEqual([result["sent_count"] for result in results], [0, 0, 0])
        self.assertFalse(self.notif_qs.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_recovers_an_abandoned_email_claim(self) -> None:
        """Retry an expired delivery claim while leaving a current claim alone."""
        # Arrange
        self._add_funding_credit(self.user, Decimal(50))
        send_funding_credits_reminders()
        reminder = self.notif_qs.get()
        self.notif_qs.update(
            extra={
                **reminder.extra,
                "email_state": "sending",
                "email_claimed_at": self.now.return_value.isoformat(),
                "email_claim_token": "abandoned",
            }
        )
        # Act
        send_funding_credits_reminders(send_email=True)
        active_claim_email_count = len(mail.outbox)
        self.now.return_value += timedelta(hours=2)
        send_funding_credits_reminders(send_email=True)
        # Assert
        self.assertEqual(active_claim_email_count, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.notif_qs.count(), 1)
        self.assertEqual(self.notif_qs.get().extra["email_state"], "sent")
        self.assertNotEqual(self.notif_qs.get().extra["email_claim_token"], "abandoned")
