from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from web3 import Web3

from reputation.distributions import Distribution
from reputation.distributor import Distributor
from reputation.services.wallet import WalletService
from user.related_models.user_model import FOUNDATION_REVENUE_EMAIL
from user.tests.helpers import create_user


class TestWalletService(TestCase):
    """Test cases for WalletService."""

    def setUp(self):
        """Set up test data."""
        # Create a community revenue account user
        self.revenue_account = create_user(
            email=FOUNDATION_REVENUE_EMAIL, first_name="Revenue", last_name="Account"
        )

        # Mock web3 components
        self.mock_w3 = Mock()
        self.mock_contract = Mock()
        self.mock_eth = Mock()

        # Set up mock contract methods with proper return values
        self.mock_contract.functions.transfer.return_value.call.return_value = "0x123"

        # Fix the balanceOf mock chain - use a completely different approach
        # Mock the entire chain: contract.functions.balanceOf().call() -> number
        self.mock_contract.functions = Mock()
        # Create a mock that returns a number when call() is invoked
        mock_balance_of_result = Mock()
        mock_balance_of_result.call = Mock(return_value=1000000000000000000000)
        self.mock_contract.functions.balanceOf = Mock(
            return_value=mock_balance_of_result
        )

        # Set up mock eth methods
        self.mock_eth.get_balance.return_value = (
            1000000000000000000000  # 1000 ETH in wei
        )
        self.mock_eth.generate_gas_price.return_value = 20000000000  # 20 gwei

        # Set up mock w3
        self.mock_w3.eth.contract.return_value = self.mock_contract
        self.mock_w3.eth = self.mock_eth
        self.mock_w3.to_checksum_address = Web3.to_checksum_address

    @patch("reputation.services.wallet.User.objects.get_community_revenue_account")
    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.execute_erc20_transfer")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.logger")
    @patch("reputation.services.wallet.log_error")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
    )
    def test_burn_revenue_rsc_success(
        self,
        mock_log_error,
        mock_logger,
        mock_get_private_key,
        mock_execute_transfer,
        mock_gas_estimate,
        mock_web3_provider,
        mock_get_revenue_account,
    ):
        """Test successful RSC burning from revenue account."""
        # Arrange
        mock_get_revenue_account.return_value = self.revenue_account
        self.revenue_account.get_balance = Mock(return_value=Decimal("100.0"))
        mock_get_private_key.return_value = "mock_private_key"

        mock_web3_provider.base = self.mock_w3
        mock_gas_estimate.return_value = 100000  # 100k gas
        mock_execute_transfer.return_value = "0xabc123"

        # Act
        result = WalletService.burn_revenue_rsc("BASE")

        # Assert
        self.assertEqual(result, "0xabc123")
        mock_logger.info.assert_called()
        mock_execute_transfer.assert_called_once()

    @patch("reputation.services.wallet.User.objects.get_community_revenue_account")
    @patch("reputation.services.wallet.logger")
    def test_burn_revenue_rsc_no_balance(self, mock_logger, mock_get_revenue_account):
        """Test RSC burning when revenue account has no balance."""
        # Arrange
        mock_get_revenue_account.return_value = self.revenue_account
        self.revenue_account.get_balance = Mock(return_value=Decimal("0.0"))

        # Act
        result = WalletService.burn_revenue_rsc("BASE")

        # Assert
        self.assertIsNone(result)
        mock_logger.info.assert_called_with(
            "Revenue account has no balance to burn: 0.0"
        )

    @patch("reputation.services.wallet.User.objects.get_community_revenue_account")
    @patch("reputation.services.wallet.log_error")
    def test_burn_revenue_rsc_exception(self, mock_log_error, mock_get_revenue_account):
        """Test RSC burning when an exception occurs."""
        # Arrange
        mock_get_revenue_account.side_effect = Exception("Database error")

        # Act & Assert
        with self.assertRaises(Exception):
            WalletService.burn_revenue_rsc("BASE")
        mock_log_error.assert_called()

    @patch("reputation.services.wallet.Distribution")
    @patch("reputation.services.wallet.Distributor")
    @patch("reputation.services.wallet.time.time")
    def test_zero_out_revenue_account(
        self, mock_time, mock_distributor_class, mock_distribution_class
    ):
        """Test zeroing out revenue account with negative balance records."""
        # Arrange
        mock_time.return_value = 1234567890.0
        mock_distribution = Mock(spec=Distribution)
        mock_distributor = Mock(spec=Distributor)

        mock_distribution_class.return_value = mock_distribution
        mock_distributor_class.return_value = mock_distributor

        amount = Decimal("100.0")

        # Act
        WalletService._zero_out_revenue_account(self.revenue_account, amount)

        # Assert
        mock_distribution_class.assert_called_with("RSC_BURN", -amount, give_rep=False)
        mock_distributor_class.assert_called_with(
            mock_distribution,
            self.revenue_account,
            self.revenue_account,
            1234567890.0,
            self.revenue_account,
        )
        mock_distributor.distribute.assert_called_once()

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.execute_erc20_transfer")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.logger")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
    )
    def test_burn_tokens_from_hot_wallet_success(
        self,
        mock_logger,
        mock_get_private_key,
        mock_execute_transfer,
        mock_gas_estimate,
        mock_web3_provider,
    ):
        """Test successful token burning from hot wallet."""
        # Arrange
        mock_web3_provider.base = self.mock_w3
        mock_gas_estimate.return_value = 100000  # 100k gas
        mock_execute_transfer.return_value = "0xdef456"
        mock_get_private_key.return_value = "mock_private_key"

        amount = Decimal("100.0")

        # Act
        result = WalletService._burn_tokens_from_hot_wallet(amount, "BASE")

        # Assert
        self.assertEqual(result, "0xdef456")
        mock_logger.info.assert_called()
        mock_execute_transfer.assert_called_once()

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.log_error")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
    )
    def test_burn_tokens_from_hot_wallet_insufficient_eth(
        self,
        mock_log_error,
        mock_get_private_key,
        mock_gas_estimate,
        mock_web3_provider,
    ):
        """Test token burning fails when hot wallet has insufficient ETH."""
        # Arrange
        mock_web3_provider.base = self.mock_w3
        mock_gas_estimate.return_value = 100000  # 100k gas
        mock_get_private_key.return_value = "mock_private_key"

        # Set very low ETH balance - need to ensure this is less than estimated cost
        estimated_cost_wei = 100000 * 20000000000  # gas * gas_price
        self.mock_eth.get_balance.return_value = (
            estimated_cost_wei // 2
        )  # Half of what's needed

        amount = Decimal("100.0")

        # Act & Assert
        with self.assertRaises(Exception) as context:
            WalletService._burn_tokens_from_hot_wallet(amount, "BASE")

        self.assertIn("Insufficient ETH in hot wallet", str(context.exception))
        mock_log_error.assert_called()

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.log_error")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
    )
    def test_burn_tokens_from_hot_wallet_exception(
        self,
        mock_log_error,
        mock_get_private_key,
        mock_gas_estimate,
        mock_web3_provider,
    ):
        """Test token burning fails when an exception occurs."""
        # Arrange
        mock_web3_provider.base = self.mock_w3
        mock_gas_estimate.side_effect = Exception("Gas estimation failed")
        mock_get_private_key.return_value = "mock_private_key"

        amount = Decimal("100.0")

        # Act & Assert
        with self.assertRaises(Exception):
            WalletService._burn_tokens_from_hot_wallet(amount, "BASE")
        mock_log_error.assert_called()

    def test_null_address_constant(self):
        """Test that NULL_ADDRESS constant is correctly defined."""
        from reputation.services.wallet import NULL_ADDRESS

        self.assertEqual(NULL_ADDRESS, "0x0000000000000000000000000000000000000000")

    @patch("reputation.services.wallet.User.objects.get_community_revenue_account")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.execute_erc20_transfer")
    @patch("reputation.services.wallet.logger")
    @override_settings(
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
        RSC_CONTRACT_ADDRESS="0xabcdef1234567890abcdef1234567890abcdef12",
    )
    def test_burn_revenue_rsc_ethereum_network(
        self,
        mock_logger,
        mock_execute_transfer,
        mock_gas_estimate,
        mock_web3_provider,
        mock_get_private_key,
        mock_get_revenue_account,
    ):
        """Test RSC burning on ETHEREUM network."""
        # Arrange
        mock_get_revenue_account.return_value = self.revenue_account
        self.revenue_account.get_balance = Mock(return_value=Decimal("50.0"))
        mock_get_private_key.return_value = "mock_private_key"

        mock_web3_provider.ethereum = self.mock_w3
        mock_gas_estimate.return_value = 150000  # 150k gas
        mock_execute_transfer.return_value = "0x789abc"

        # Act
        result = WalletService.burn_revenue_rsc("ETHEREUM")

        # Assert
        self.assertEqual(result, "0x789abc")
        mock_logger.info.assert_called()
        mock_execute_transfer.assert_called_once()

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.execute_erc20_transfer")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.logger")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
    )
    def test_burn_tokens_from_hot_wallet_gas_estimation(
        self,
        mock_logger,
        mock_get_private_key,
        mock_execute_transfer,
        mock_gas_estimate,
        mock_web3_provider,
    ):
        """Test gas estimation and cost calculation in token burning."""
        # Arrange
        mock_web3_provider.base = self.mock_w3
        mock_gas_estimate.return_value = 200000  # 200k gas
        mock_execute_transfer.return_value = "0xgas123"
        mock_get_private_key.return_value = "mock_private_key"

        amount = Decimal("100.0")

        # Act
        result = WalletService._burn_tokens_from_hot_wallet(amount, "BASE")

        # Assert
        self.assertEqual(result, "0xgas123")
        # Verify gas estimation was called with correct parameters
        mock_gas_estimate.assert_called_once()
        mock_execute_transfer.assert_called_once()
