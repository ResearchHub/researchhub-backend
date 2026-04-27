from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytz
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from notification.models import Notification
from purchase.circle.client import CircleTransferError
from purchase.models import Fundraise, Wallet
from purchase.services.fundraise_service import FundraiseService
from purchase.tasks import (
    complete_eligible_fundraises,
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
        from purchase.models import RscExchangeRate

        self.rsc_exchange_rate = RscExchangeRate.objects.create(
            rate=0.5,  # 1 USD = 2 RSC
            real_rate=0.5,
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        self.exchange_rate_patcher = patch(
            "purchase.related_models.rsc_exchange_rate_model."
            "RscExchangeRate.get_latest",
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
        old_date = datetime.now(pytz.UTC) - timedelta(days=8)
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
        old_date = datetime.now(pytz.UTC) - timedelta(days=8)
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

    def test_complete_eligible_fundraises_uses_3_day_average_rate(self):
        """Closeout should value RSC at the 3-day average rate, not the latest spike."""
        from purchase.models import RscExchangeRate

        # Stop the get_latest patcher set up in setUp so the task path
        # exercises the real get_average_rate query.
        self.exchange_rate_patcher.stop()
        self.addCleanup(self.exchange_rate_patcher.start)

        # Historical rates over the last 3 days average to 0.5 ($/RSC).
        # Today there's an extreme spike (rate=2.0). Under the latest rate,
        # 100 RSC would be worth $200 and would clear a $100 goal — but the
        # 3-day average values it at $50, so the goal should NOT be met.
        for days_ago, rate in [(2, 0.5), (1, 0.5), (0, 2.0)]:
            obj = RscExchangeRate.objects.create(
                rate=rate,
                real_rate=rate,
                price_source="COIN_GECKO",
                target_currency="USD",
            )
            backdated = datetime.now(pytz.UTC) - timedelta(days=days_ago)
            RscExchangeRate.objects.filter(pk=obj.pk).update(created_date=backdated)

        fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )
        old_date = datetime.now(pytz.UTC) - timedelta(days=8)
        fundraise.start_date = old_date
        fundraise.save()

        # 100 RSC: avg-rate value = $50 (under goal), latest value = $200 (over).
        fundraise.escrow.amount_holding = Decimal("100.00")
        fundraise.escrow.save()

        result = complete_eligible_fundraises()

        self.assertEqual(result["completed_count"], 0)
        fundraise.refresh_from_db()
        self.assertEqual(fundraise.status, Fundraise.OPEN)

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
        self.future = datetime.now(pytz.UTC) + timedelta(days=30)
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
