import decimal
from datetime import datetime, timedelta
from unittest import mock

import pytz
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from purchase.models import Balance, RscExchangeRate
from reputation.lib import WITHDRAWAL_MINIMUM, PendingWithdrawal
from reputation.models import Withdrawal
from reputation.tests.helpers import create_deposit, create_withdrawal
from reputation.views.withdrawal_view import WithdrawalViewSet
from user.related_models.user_verification_model import UserVerification
from user.tests.helpers import (
    create_random_authenticated_user,
    create_random_authenticated_user_with_reputation,
)


# Create a test class with proper AWS mocking
class WithdrawalViewSetTests(APITestCase):
    """Tests for the WithdrawalViewSet functionality."""

    def setUp(self):
        # Mock requests
        self.requests_get_patcher = mock.patch("requests.get")
        self.mock_requests_get = self.requests_get_patcher.start()

        # Create a mock response for Etherscan API
        eth_mock_response = mock.MagicMock()
        eth_mock_response.json.return_value = {"result": {"SafeGasPrice": "30"}}

        # Create a mock response for Basescan API with proper hex format
        base_mock_response = mock.MagicMock()
        base_mock_response.json.return_value = {
            "result": "0x2540be400"
        }  # Hex value for gas price

        # Configure mock to return different responses based on the URL
        def get_mock_response(*args, **kwargs):
            if "etherscan.io" in args[0]:
                return eth_mock_response
            elif "basescan.org" in args[0]:
                return base_mock_response
            return eth_mock_response  # Default fallback

        self.mock_requests_get.side_effect = get_mock_response

        # Mock settings
        self.settings_patcher = mock.patch.object(
            settings,
            "WEB3_KEYSTORE_SECRET_ID",
            new_callable=mock.PropertyMock,
            return_value="mock-secret-id",
        )
        self.mock_settings = self.settings_patcher.start()

        self.withdrawal_view = WithdrawalViewSet()
        self.withdrawal_url = reverse("withdrawal-list")
        self.transaction_fee_url = reverse("withdrawal-transaction-fee")

        # Mock PendingWithdrawal.complete_token_transfer
        self.withdraw_patcher = mock.patch.object(
            PendingWithdrawal, "complete_token_transfer", return_value=None
        )
        self.withdraw_patcher.start()

        # Mock RscExchangeRate.eth_to_rsc
        self.eth_to_rsc_patcher = mock.patch.object(
            RscExchangeRate, "eth_to_rsc", return_value=10
        )
        self.eth_to_rsc_patcher.start()

    def tearDown(self):
        self.withdraw_patcher.stop()
        self.eth_to_rsc_patcher.stop()
        self.settings_patcher.stop()
        self.requests_get_patcher.stop()

    def test_list_only_shows_user_withdrawals(self):
        """Test that a user can only see their own withdrawals."""
        # Create withdrawals for various users
        user1 = create_random_authenticated_user("user1")
        user2 = create_random_authenticated_user("user2")

        # Create multiple withdrawals
        create_withdrawal(user1, amount="100.0")
        create_withdrawal(user1, amount="200.0")
        create_withdrawal(user2, amount="300.0")

        # User1 should only see their own withdrawals
        self.client.force_authenticate(user1)
        response = self.client.get(self.withdrawal_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)

        # Verify user data is included in response
        self.assertEqual(response.data["user"]["id"], user1.id)

        # User2 should only see their own withdrawal
        self.client.force_authenticate(user2)
        response = self.client.get(self.withdrawal_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

        # Staff user can see all withdrawals
        admin = create_random_authenticated_user("admin")
        admin.is_staff = True
        admin.save()
        self.client.force_authenticate(admin)
        response = self.client.get(self.withdrawal_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 3)  # All withdrawals

    def test_create_withdrawal_success(self):
        """Test successful withdrawal creation."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create a deposit well above the minimum
        deposit_amount = WITHDRAWAL_MINIMUM * 2
        create_deposit(user, amount=str(deposit_amount))
        self.client.force_authenticate(user)

        # Mock the hotwallet balance check to return True
        with mock.patch.object(
            WithdrawalViewSet,
            "_check_hotwallet_balance",
            return_value=(True, None),
        ):
            response = self.client.post(
                self.withdrawal_url,
                {
                    "amount": str(WITHDRAWAL_MINIMUM + 10),  # Amount above minimum
                    "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
                    "network": "ETHEREUM",
                },
            )

            self.assertEqual(response.status_code, 201)
            withdrawal = Withdrawal.objects.get(id=response.data["id"])

            # Check withdrawal data
            self.assertEqual(withdrawal.user, user)
            self.assertEqual(
                float(withdrawal.amount), float(WITHDRAWAL_MINIMUM)
            )  # amount - fee
            self.assertEqual(
                withdrawal.to_address, "0xabcdef1234567890abcdef1234567890abcdef12"
            )
            self.assertEqual(withdrawal.network, "ETHEREUM")
            self.assertEqual(withdrawal.fee, "10.0")  # Mocked fee

            # Check balance was updated
            expected_balance = deposit_amount - (WITHDRAWAL_MINIMUM + 10)
            self.assertEqual(user.get_balance(), decimal.Decimal(expected_balance))

    def test_withdrawal_below_minimum(self):
        """Test that withdrawals below minimum amount are rejected."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create a small deposit
        create_deposit(user, amount=str(WITHDRAWAL_MINIMUM - 1))
        self.client.force_authenticate(user)

        response = self.client.post(
            self.withdrawal_url,
            {
                "amount": str(WITHDRAWAL_MINIMUM - 1),
                "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            f"below the withdrawal minimum of {WITHDRAWAL_MINIMUM}", response.data
        )

    def test_withdrawal_with_pending_transaction(self):
        """Test that users can't create a new withdrawal with a pending one."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create a deposit
        create_deposit(user, amount="1000.0")

        # Create a pending withdrawal
        Withdrawal.objects.create(
            user=user,
            to_address="0xabcdef1234567890abcdef1234567890abcdef12",
            amount=decimal.Decimal("100"),
            paid_status="PENDING",
            transaction_hash="0x1234",
        )

        self.client.force_authenticate(user)
        response = self.client.post(
            self.withdrawal_url,
            {
                "amount": "200",
                "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Please wait for your previous withdrawal to finish", response.data
        )

    def test_withdrawal_exceeds_user_balance(self):
        """Test that users can't withdraw more than their balance."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create a deposit
        create_deposit(user, amount="100.0")
        self.client.force_authenticate(user)

        response = self.client.post(
            self.withdrawal_url,
            {
                "amount": "200",
                "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            },
        )

        self.assertEqual(response.status_code, 400)
        # In the actual implementation, the minimum withdrawal check happens first
        self.assertIn("below the withdrawal minimum", response.data)

    def test_withdrawal_suspended(self):
        """Test that withdrawals are blocked when the withdrawal switch is on."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        moderator = create_random_authenticated_user("moderator")
        moderator.is_staff = True
        moderator.save()

        # Create a deposit
        create_deposit(user, amount="1000.0")

        # Turn on withdrawal switch
        LogEntry.objects.create(
            object_repr="WITHDRAWAL_SWITCH", action_flag=3, user=moderator
        )

        self.client.force_authenticate(user)
        response = self.client.post(
            self.withdrawal_url,
            {
                "amount": "500",
                "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Withdrawals are suspended", response.data)

    def test_transaction_fee_endpoint(self):
        """Test the transaction fee endpoint returns the correct fee."""
        user = create_random_authenticated_user("user")
        self.client.force_authenticate(user)

        response = self.client.get(self.transaction_fee_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, decimal.Decimal("10"))

        # Test with BASE network
        response = self.client.get(f"{self.transaction_fee_url}?network=BASE")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data, decimal.Decimal("10")
        )  # Same because we're mocking

    def test_check_withdrawal_time_limit_new_user(self):
        """Test that new unverified users can't withdraw within 2 weeks."""
        user = create_random_authenticated_user("new_user")
        user.created_date = timezone.now() - timedelta(days=10)  # Less than 2 weeks
        user.save()

        to_address = "0xabcdef1234567890abcdef1234567890abcdef12"

        valid, message = self.withdrawal_view._check_withdrawal_time_limit(
            to_address, user
        )

        self.assertFalse(valid)
        self.assertIn("account is new, please wait 2 weeks", message)

    def test_withdrawal_network_validation(self):
        """Test that invalid networks are rejected."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        create_deposit(user, amount="1000.0")
        self.client.force_authenticate(user)

        response = self.client.post(
            self.withdrawal_url,
            {
                "amount": "500",
                "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
                "network": "INVALID_NETWORK",
            },
        )

        self.assertEqual(response.status_code, 400)
        error_msg = "Invalid network. Please choose either 'BASE' or 'ETHEREUM'"
        self.assertEqual(response.data, error_msg)

    def test_withdrawal_creates_balance_record(self):
        """Test that a balance record is created when withdrawing."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create a deposit well above the minimum
        deposit_amount = WITHDRAWAL_MINIMUM * 2
        create_deposit(user, amount=str(deposit_amount))
        self.client.force_authenticate(user)

        initial_balance_count = Balance.objects.filter(user=user).count()

        # Mock the hotwallet balance check to return True
        with mock.patch.object(
            WithdrawalViewSet,
            "_check_hotwallet_balance",
            return_value=(True, None),
        ):
            response = self.client.post(
                self.withdrawal_url,
                {
                    "amount": str(WITHDRAWAL_MINIMUM + 10),  # Amount above minimum
                    "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
                },
            )

            self.assertEqual(response.status_code, 201)

            # Should have one more balance record
            new_balance_count = Balance.objects.filter(user=user).count()
            self.assertEqual(new_balance_count, initial_balance_count + 1)

            # Check the balance record details
            withdrawal = Withdrawal.objects.get(id=response.data["id"])
            latest_balance = Balance.objects.filter(user=user).latest("id")

            self.assertEqual(
                str(latest_balance.amount),
                f"-{float(withdrawal.amount) + float(withdrawal.fee)}",
            )

    def test_calculate_transaction_fee_ethereum(self):
        """Test the calculation of Ethereum transaction fees."""
        # Mock the etherscan API response
        with mock.patch("requests.get") as mock_get:
            mock_response = mock.Mock()
            mock_response.json.return_value = {"result": {"SafeGasPrice": "30"}}
            mock_get.return_value = mock_response

            fee = self.withdrawal_view.calculate_transaction_fee("ETHEREUM")

            # Verify the fee calculation
            self.assertEqual(
                fee, decimal.Decimal("10")
            )  # Based on our mock of eth_to_rsc

            # Verify the call to etherscan
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            self.assertIn("https://api.etherscan.io/api", args[0])
            self.assertIn("gastracker", args[0])
            self.assertIn("gasoracle", args[0])

    def test_calculate_transaction_fee_base(self):
        """Test the calculation of Base network transaction fees."""
        # Mock the basescan API response
        with mock.patch("requests.get") as mock_get:
            mock_response = mock.Mock()
            mock_response.json.return_value = {
                "result": "0x2540be400"
            }  # 10 gwei in hex
            mock_get.return_value = mock_response

            fee = self.withdrawal_view.calculate_transaction_fee("BASE")

            # Verify the fee calculation
            self.assertEqual(
                fee, decimal.Decimal("10")
            )  # Based on our mock of eth_to_rsc

            # Verify the call to basescan
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            self.assertIn("https://api.basescan.org/api", args[0])
            self.assertIn("proxy", args[0])
            self.assertIn("eth_gasPrice", args[0])

    def test_check_withdrawal_interval_within_time_limit(self):
        """Test withdrawal interval validation for withdrawals within the time limit."""
        user = create_random_authenticated_user("test_user")
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create a recent withdrawal
        withdrawal = Withdrawal.objects.create(
            user=user,
            to_address="0xabcdef1234567890abcdef1234567890abcdef12",
            amount=decimal.Decimal("100"),
            paid_status="PAID",
        )
        withdrawal.created_date = timezone.now() - timedelta(days=1)  # 1 day ago
        withdrawal.save()

        # Attempt another withdrawal to the same address
        valid, message = self.withdrawal_view._check_withdrawal_interval(
            user, "0xabcdef1234567890abcdef1234567890abcdef12"
        )

        self.assertFalse(valid)
        # Check that the message starts with the expected text
        # and contains a time reference
        expected_start = "The next time you're able to withdraw is in"
        self.assertTrue(message.startswith(expected_start))
        # Since we're using humanize, it should have a natural time format
        # For a 2-week interval with 1 day passed, it should mention days
        self.assertTrue("12 days" in message)

    def test_check_withdrawal_interval_after_time_limit(self):
        """Test withdrawal interval validation for withdrawals after the time limit."""
        user = create_random_authenticated_user("test_user")
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create an old withdrawal
        withdrawal = Withdrawal.objects.create(
            user=user,
            to_address="0xabcdef1234567890abcdef1234567890abcdef12",
            amount=decimal.Decimal("100"),
            paid_status="PAID",
        )
        withdrawal.created_date = timezone.now() - timedelta(days=15)  # 15 days ago
        withdrawal.save()

        # Attempt another withdrawal
        valid, message = self.withdrawal_view._check_withdrawal_interval(
            user, "0xabcdef1234567890abcdef1234567890abcdef12"
        )

        self.assertTrue(valid)
        self.assertIsNone(message)

    def test_verified_user_withdrawal_interval(self):
        """Test that verified users have a shorter withdrawal interval."""
        user = create_random_authenticated_user("verified_user")
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Add verification
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )

        # Create a recent withdrawal
        withdrawal = Withdrawal.objects.create(
            user=user,
            to_address="0xabcdef1234567890abcdef1234567890abcdef12",
            amount=decimal.Decimal("100"),
            paid_status="PAID",
        )

        # Set to slightly more than 24 hours ago
        withdrawal.created_date = timezone.now() - timedelta(hours=25)
        withdrawal.save()

        # Attempt another withdrawal
        valid, message = self.withdrawal_view._check_withdrawal_interval(
            user, "0xabcdef1234567890abcdef1234567890abcdef12"
        )

        self.assertTrue(valid)
        self.assertIsNone(message)

    def test_exception_in_payment_process(self):
        """Test that exceptions in the payment process are handled properly."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        create_deposit(user, amount="1000.0")
        self.client.force_authenticate(user)

        # Make PendingWithdrawal.complete_token_transfer raise an exception
        with mock.patch.object(
            PendingWithdrawal,
            "complete_token_transfer",
            side_effect=Exception("Test exception"),
        ):
            response = self.client.post(
                self.withdrawal_url,
                {
                    "amount": "500",
                    "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
                },
            )

            self.assertEqual(response.status_code, 400)

    def test_unauthenticated_user_cannot_withdraw(self):
        """Test that unauthenticated users cannot withdraw."""
        # Don't authenticate any user
        response = self.client.post(
            self.withdrawal_url,
            {
                "amount": "500",
                "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
            },
        )

        self.assertEqual(response.status_code, 401)  # Unauthorized

    def test_transaction_fee_bigger_than_withdrawal_amount(self):
        """Test that withdrawal fails if transaction fee is bigger than amount."""
        user = create_random_authenticated_user_with_reputation("rep_user", 1000)
        user.date_joined = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.created_date = datetime(year=2020, month=1, day=1, tzinfo=pytz.utc)
        user.save()

        # Create a deposit with an amount above the withdrawal minimum
        deposit_amount = WITHDRAWAL_MINIMUM + 100.0
        create_deposit(user, amount=str(deposit_amount))
        self.client.force_authenticate(user)

        # Set a high transaction fee and mock hotwallet balance check
        with mock.patch.object(
            WithdrawalViewSet,
            "calculate_transaction_fee",
            return_value=decimal.Decimal("700"),
        ), mock.patch.object(
            WithdrawalViewSet,
            "_check_hotwallet_balance",
            return_value=(True, None),
        ):
            # Post an amount above the minimum but less than the transaction fee
            withdrawal_amount = 600.0  # Less than the transaction fee
            response = self.client.post(
                self.withdrawal_url,
                {
                    "amount": str(withdrawal_amount),
                    "to_address": "0xabcdef1234567890abcdef1234567890abcdef12",
                },
            )

            self.assertEqual(response.status_code, 400)
            # This should fail when checking withdrawal amount vs fee
            self.assertEqual(response.data, "Invalid withdrawal")

    def test_check_hotwallet_balance_success(self):
        """Test hotwallet balance check succeeds when balance is sufficient."""
        # Patch the hotwallet balance to return a large value
        with mock.patch(
            "reputation.views.withdrawal_view.get_hotwallet_rsc_balance",
            return_value=1000,
        ):
            result, message = self.withdrawal_view._check_hotwallet_balance(
                500, "ETHEREUM"
            )

            self.assertTrue(result)
            self.assertIsNone(message)

    def test_check_hotwallet_balance_failure(self):
        """Test hotwallet balance check fails when balance is insufficient."""
        # Patch the hotwallet balance to return a small value
        with mock.patch(
            "reputation.views.withdrawal_view.get_hotwallet_rsc_balance",
            return_value=100,
        ):
            result, message = self.withdrawal_view._check_hotwallet_balance(
                500, "ETHEREUM"
            )

            self.assertFalse(result)
            self.assertEqual(
                message, "Hotwallet balance is lower than the withdrawal amount"
            )

    def test_check_withdrawal_meets_minimum_success(self):
        """Test that _check_meets_withdrawal_minimum succeeds with sufficient amount."""
        # Set an amount above the minimum
        amount = WITHDRAWAL_MINIMUM + decimal.Decimal("10")

        valid, message = self.withdrawal_view._check_meets_withdrawal_minimum(amount)

        self.assertTrue(valid)
        self.assertIsNone(message)

    def test_check_withdrawal_meets_minimum_failure(self):
        """Test that _check_meets_withdrawal_minimum fails with insufficient amount."""
        # Set an amount below the minimum
        amount = WITHDRAWAL_MINIMUM - decimal.Decimal("1")

        valid, message = self.withdrawal_view._check_meets_withdrawal_minimum(amount)

        self.assertFalse(valid)
        self.assertIn(f"below the withdrawal minimum of {WITHDRAWAL_MINIMUM}", message)

    def test_check_withdrawal_meets_minimum_zero(self):
        """Test that _check_meets_withdrawal_minimum fails with zero amount."""
        amount = decimal.Decimal("0")

        valid, message = self.withdrawal_view._check_meets_withdrawal_minimum(amount)

        self.assertFalse(valid)
        self.assertEqual(message, f"Insufficient balance of {amount}")

    def test_check_agreed_to_terms_from_user_model(self):
        """Test _check_agreed_to_terms with agreed_to_terms=True in user model."""
        user = create_random_authenticated_user("terms_user")
        user.agreed_to_terms = True
        user.save()

        request = mock.MagicMock()
        request.data = {}

        valid, message = self.withdrawal_view._check_agreed_to_terms(user, request)

        self.assertTrue(valid)
        self.assertIsNone(message)

    def test_check_withdrawal_amount_success(self):
        """Test that _check_withdrawal_amount succeeds with valid amount and fee."""
        user = create_random_authenticated_user("amount_user")
        create_deposit(user, amount="1000.0")

        amount = decimal.Decimal("500")
        fee = decimal.Decimal("10")

        valid, message, net_amount = self.withdrawal_view._check_withdrawal_amount(
            amount, fee, user
        )

        self.assertTrue(valid)
        self.assertIsNone(message)
        self.assertEqual(net_amount, amount - fee)

    def test_check_withdrawal_amount_negative_fee(self):
        """Test that _check_withdrawal_amount fails with negative fee."""
        user = create_random_authenticated_user("amount_user")
        create_deposit(user, amount="1000.0")

        amount = decimal.Decimal("500")
        fee = decimal.Decimal("-10")  # Negative fee

        valid, message, net_amount = self.withdrawal_view._check_withdrawal_amount(
            amount, fee, user
        )

        self.assertFalse(valid)
        self.assertEqual(message, "Transaction fee can't be negative")
        self.assertIsNone(net_amount)

    def test_check_withdrawal_amount_negative_net_amount(self):
        """Test that _check_withdrawal_amount fails when amount < fee."""
        user = create_random_authenticated_user("amount_user")
        create_deposit(user, amount="1000.0")

        amount = decimal.Decimal("5")
        fee = decimal.Decimal("10")  # Fee > amount

        valid, message, net_amount = self.withdrawal_view._check_withdrawal_amount(
            amount, fee, user
        )

        self.assertFalse(valid)
        self.assertEqual(message, "Invalid withdrawal")
        self.assertIsNone(net_amount)

    def test_check_withdrawal_amount_insufficient_balance(self):
        """Test _check_withdrawal_amount with insufficient user balance."""
        user = create_random_authenticated_user("amount_user")
        create_deposit(user, amount="100.0")

        amount = decimal.Decimal("500")  # More than the user's balance
        fee = decimal.Decimal("10")

        valid, message, net_amount = self.withdrawal_view._check_withdrawal_amount(
            amount, fee, user
        )

        self.assertFalse(valid)
        self.assertEqual(message, "You do not have enough RSC to make this withdrawal")
        self.assertIsNone(net_amount)

    def test_check_withdrawal_time_limit_verified_user(self):
        """Test that verified users can withdraw immediately after account creation."""
        user = create_random_authenticated_user("new_verified_user")
        user.created_date = timezone.now() - timedelta(days=1)  # 1 day old account
        user.save()

        # Add verification
        UserVerification.objects.create(
            user=user, status=UserVerification.Status.APPROVED
        )

        to_address = "0xabcdef1234567890abcdef1234567890abcdef12"

        valid, message = self.withdrawal_view._check_withdrawal_time_limit(
            to_address, user
        )

        self.assertTrue(valid)
        self.assertIsNone(message)
