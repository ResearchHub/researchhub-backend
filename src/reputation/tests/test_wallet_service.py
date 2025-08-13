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

        self.mock_contract.functions = Mock()
        mock_balance_of_result = Mock()
        mock_balance_of_result.call = Mock(return_value=1000000000000000000000)
        self.mock_contract.functions.balanceOf = Mock(
            return_value=mock_balance_of_result
        )

        # Set up mock eth methods
        self.mock_eth.get_balance.return_value = (
            1000000000000000000000  # 1000 ETH in wei
        )

        # Set up mock w3
        self.mock_w3.eth.contract.return_value = self.mock_contract
        self.mock_w3.eth = self.mock_eth
        self.mock_w3.to_checksum_address = Web3.to_checksum_address

        # Mock requests for gas price API calls
        self.requests_get_patcher = patch("reputation.services.wallet.requests.get")
        self.mock_requests_get = self.requests_get_patcher.start()

        # Create mock responses for different networks
        self.eth_mock_response = Mock()
        self.eth_mock_response.json.return_value = {"result": {"SafeGasPrice": "30"}}

        self.base_mock_response = Mock()
        self.base_mock_response.json.return_value = {
            "result": "0x2540be400"  # 10 gwei in hex
        }

        # Configure mock to return different responses based on the URL
        def get_mock_response(*args, **kwargs):
            if "etherscan.io/v2/api?chainid=1" in args[0]:
                return self.eth_mock_response
            elif "etherscan.io/v2/api?chainid=8453" in args[0]:
                return self.base_mock_response
            return self.eth_mock_response  # Default fallback

        self.mock_requests_get.side_effect = get_mock_response

    def tearDown(self):
        """Clean up mocks."""
        self.requests_get_patcher.stop()

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
        ETHERSCAN_API_KEY="test_api_key",
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

        # Verify API calls were made for gas price
        self.mock_requests_get.assert_called()
        # Should have called the BASE network API
        base_api_calls = [
            call_args
            for call_args in self.mock_requests_get.call_args_list
            if "chainid=8453" in str(call_args)
        ]
        self.assertTrue(len(base_api_calls) > 0)

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
        ETHERSCAN_API_KEY="test_api_key",
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

        # Verify API call was made for gas price
        self.mock_requests_get.assert_called_once()
        args, kwargs = self.mock_requests_get.call_args
        self.assertIn("https://api.etherscan.io/v2/api?chainid=8453", args[0])
        self.assertIn("proxy", args[0])
        self.assertIn("eth_gasPrice", args[0])

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.log_error")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
        ETHERSCAN_API_KEY="test_api_key",
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

        # Set ETH balance to be insufficient
        # Gas price from mock API: 0x2540be400 = 10000000000 wei (10 gwei)
        gas_price_wei = 10000000000
        estimated_cost_wei = 100000 * gas_price_wei
        self.mock_eth.get_balance.return_value = (
            estimated_cost_wei // 2
        )  # 50% of required

        amount = Decimal("100.0")

        # Act & Assert
        with self.assertRaises(Exception) as context:
            WalletService._burn_tokens_from_hot_wallet(amount, "BASE")

        self.assertIn("Insufficient ETH in hot wallet", str(context.exception))
        mock_log_error.assert_called()

        # Verify API call was made for gas price
        self.mock_requests_get.assert_called_once()

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.log_error")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
        ETHERSCAN_API_KEY="test_api_key",
    )
    def test_burn_tokens_from_hot_wallet_api_failure(
        self,
        mock_log_error,
        mock_get_private_key,
        mock_gas_estimate,
        mock_web3_provider,
    ):
        """Test handling of API failure when getting gas price."""
        # Arrange
        mock_web3_provider.base = self.mock_w3
        mock_gas_estimate.return_value = 100000
        mock_get_private_key.return_value = "mock_private_key"

        # Mock API failure
        self.mock_requests_get.side_effect = Exception("API timeout")

        amount = Decimal("100.0")

        # Act & Assert
        with self.assertRaises(Exception):
            WalletService._burn_tokens_from_hot_wallet(amount, "BASE")
        mock_log_error.assert_called()

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.execute_erc20_transfer")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.logger")
    @override_settings(
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
        ETHERSCAN_API_KEY="test_api_key",
    )
    def test_burn_tokens_from_hot_wallet_ethereum_network(
        self,
        mock_logger,
        mock_get_private_key,
        mock_execute_transfer,
        mock_gas_estimate,
        mock_web3_provider,
    ):
        """Test RSC burning on ETHEREUM network."""
        # Arrange
        mock_web3_provider.ethereum = self.mock_w3
        mock_gas_estimate.return_value = 150000  # 150k gas
        mock_execute_transfer.return_value = "0x789abc"
        mock_get_private_key.return_value = "mock_private_key"

        amount = Decimal("50.0")

        # Act
        result = WalletService._burn_tokens_from_hot_wallet(amount, "ETHEREUM")

        # Assert
        self.assertEqual(result, "0x789abc")
        mock_logger.info.assert_called()
        mock_execute_transfer.assert_called_once()

        # Verify API call was made for gas price
        self.mock_requests_get.assert_called_once()
        args, kwargs = self.mock_requests_get.call_args
        self.assertIn("https://api.etherscan.io/v2/api?chainid=1", args[0])
        self.assertIn("gastracker", args[0])
        self.assertIn("gasoracle", args[0])

    def test_null_address_constant(self):
        """Test that NULL_ADDRESS constant is correctly defined."""
        from reputation.services.wallet import NULL_ADDRESS

        self.assertEqual(NULL_ADDRESS, "0x0000000000000000000000000000000000000000")

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.execute_erc20_transfer")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.logger")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
        ETHERSCAN_API_KEY="test_api_key",
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

        # Verify API call was made for gas price
        self.mock_requests_get.assert_called_once()
        args, kwargs = self.mock_requests_get.call_args
        self.assertIn("chainid=8453", args[0])

    @patch("reputation.services.wallet.web3_provider")
    @patch("reputation.services.wallet.get_gas_estimate")
    @patch("reputation.services.wallet.get_private_key")
    @patch("reputation.services.wallet.log_error")
    @override_settings(
        WEB3_BASE_RSC_ADDRESS="0x1234567890123456789012345678901234567890",
        WEB3_WALLET_ADDRESS="0x0987654321098765432109876543210987654321",
        ETHERSCAN_API_KEY="test_api_key",
    )
    def test_burn_tokens_from_hot_wallet_invalid_api_response(
        self,
        mock_log_error,
        mock_get_private_key,
        mock_gas_estimate,
        mock_web3_provider,
    ):
        """Test handling of invalid API response when getting gas price."""
        # Arrange
        mock_web3_provider.base = self.mock_w3
        mock_gas_estimate.return_value = 100000
        mock_get_private_key.return_value = "mock_private_key"

        # Mock invalid API response
        invalid_response = Mock()
        invalid_response.json.return_value = {"result": "invalid_hex"}
        self.mock_requests_get.return_value = invalid_response

        amount = Decimal("100.0")

        # Act & Assert
        with self.assertRaises(Exception):
            WalletService._burn_tokens_from_hot_wallet(amount, "BASE")
        mock_log_error.assert_called()
