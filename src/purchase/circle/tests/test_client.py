import json
from decimal import Decimal
from unittest.mock import Mock

from circle.web3.developer_controlled_wallets import ApiClient, Configuration
from circle.web3.developer_controlled_wallets.api import WalletsApi
from circle.web3.developer_controlled_wallets.exceptions import OpenApiException
from django.test import TestCase
from urllib3 import HTTPResponse

from purchase.circle.client import (
    CircleBalanceError,
    CircleTransferError,
    CircleWalletClient,
    CircleWalletCreationError,
    CircleWalletCreationResult,
)


class TestCircleWalletClient(TestCase):
    """Tests for CircleWalletClient."""

    def _make_client(self, mock_wallets_api=None, mock_transactions_api=None):
        """Create a CircleWalletClient with mocked APIs."""
        client = CircleWalletClient.__new__(CircleWalletClient)
        client._api_client = Mock()
        client._wallets_api = mock_wallets_api
        client._transactions_api = mock_transactions_api
        return client

    def _make_sdk_wallets_api(self, body, status=200):
        """
        Create a real SDK WalletsApi whose HTTP layer returns ``body``.

        Exercises the SDK's request/response handling end to end, so
        payloads its pydantic models would reject still reach our parsing.
        """
        api_client = ApiClient(Configuration(access_token="test-token"))
        api_client.rest_client.pool_manager = Mock()
        api_client.rest_client.pool_manager.request.return_value = HTTPResponse(
            body=json.dumps(body).encode(),
            status=status,
            headers={"Content-Type": "application/json"},
            preload_content=False,
        )
        return WalletsApi(api_client)

    def _make_wallet_payload(self, **kwargs):
        """Create a raw Circle SCA wallet payload."""
        return {
            "id": kwargs.get("id", "4c2ba4e6-2a5a-4bfa-9f7a-7a3b6c1c8f01"),
            "address": kwargs.get("address", "0xabc123"),
            "blockchain": kwargs.get("blockchain", "ETH"),
            "state": kwargs.get("state", "LIVE"),
            "walletSetId": "0f2c8a1e-9d3b-4b7e-8a5c-1e2d3f4a5b6c",
            "custodyType": "DEVELOPER",
            "accountType": "SCA",
            "scaCore": kwargs.get("sca_core", "circle_6900_singleowner_v3"),
            "updateDate": "2026-10-22T01:40:00Z",
            "createDate": "2026-10-22T01:40:00Z",
        }

    def _make_wallets_body(self, wallets):
        return {"data": {"wallets": wallets}}

    def _make_wallet_pair(self, eth_id="eth-wallet-1", base_id="base-wallet-1"):
        """Create a pair of raw wallet payloads (ETH + BASE)."""
        return [
            self._make_wallet_payload(id=eth_id, blockchain="ETH"),
            self._make_wallet_payload(id=base_id, blockchain="BASE"),
        ]

    def test_create_wallet_returns_both_wallet_ids(self):
        # Arrange
        wallets = self._make_wallet_pair(eth_id="eth-uuid-1", base_id="base-uuid-1")
        mock_api = self._make_sdk_wallets_api(self._make_wallets_body(wallets), 201)
        client = self._make_client(mock_api)

        # Act
        result = client.create_wallet(idempotency_key="test-key-1")

        # Assert
        self.assertIsInstance(result, CircleWalletCreationResult)
        self.assertEqual(result.eth_wallet_id, "eth-uuid-1")
        self.assertEqual(result.base_wallet_id, "base-uuid-1")

    def test_create_wallet_accepts_sca_core_unknown_to_sdk(self):
        """Wallets on an SCA core newer than the SDK's models still parse."""
        # Arrange
        wallets = [
            self._make_wallet_payload(
                id="eth-v4", blockchain="ETH", sca_core="circle_6900_singleowner_v4"
            ),
            self._make_wallet_payload(
                id="base-v4", blockchain="BASE", sca_core="circle_6900_singleowner_v4"
            ),
        ]
        mock_api = self._make_sdk_wallets_api(self._make_wallets_body(wallets), 201)
        client = self._make_client(mock_api)

        # Act
        result = client.create_wallet(idempotency_key="test-key-1")

        # Assert
        self.assertEqual(result.eth_wallet_id, "eth-v4")
        self.assertEqual(result.base_wallet_id, "base-v4")

    def test_create_wallet_handles_reversed_order(self):
        """Wallet IDs are mapped by blockchain, not by array position."""
        # Arrange
        # Return BASE first, then ETH
        wallets = [
            self._make_wallet_payload(id="base-first", blockchain="BASE"),
            self._make_wallet_payload(id="eth-second", blockchain="ETH"),
        ]
        mock_api = self._make_sdk_wallets_api(self._make_wallets_body(wallets), 201)
        client = self._make_client(mock_api)

        # Act
        result = client.create_wallet()

        # Assert
        self.assertEqual(result.eth_wallet_id, "eth-second")
        self.assertEqual(result.base_wallet_id, "base-first")

    def test_create_wallet_maps_testnet_blockchains(self):
        # Arrange
        wallets = [
            self._make_wallet_payload(id="eth-test", blockchain="ETH-SEPOLIA"),
            self._make_wallet_payload(id="base-test", blockchain="BASE-SEPOLIA"),
        ]
        mock_api = self._make_sdk_wallets_api(self._make_wallets_body(wallets), 201)
        client = self._make_client(mock_api)

        # Act
        result = client.create_wallet()

        # Assert
        self.assertEqual(result.eth_wallet_id, "eth-test")
        self.assertEqual(result.base_wallet_id, "base-test")

    def test_create_wallet_empty_response_raises(self):
        # Arrange
        mock_api = self._make_sdk_wallets_api(self._make_wallets_body([]), 201)
        client = self._make_client(mock_api)

        # Act & Assert
        with self.assertRaises(CircleWalletCreationError):
            client.create_wallet()

    def test_create_wallet_missing_one_chain_raises(self):
        """If Circle only returns one chain's wallet, raise an error."""
        # Arrange
        wallets = [self._make_wallet_payload(id="eth-only", blockchain="ETH")]
        mock_api = self._make_sdk_wallets_api(self._make_wallets_body(wallets), 201)
        client = self._make_client(mock_api)

        # Act & Assert
        with self.assertRaises(CircleWalletCreationError):
            client.create_wallet()

    def test_create_wallet_api_error_raises(self):
        # Arrange
        mock_api = self._make_sdk_wallets_api(
            {"code": 2, "message": "API parameter invalid"}, 400
        )
        client = self._make_client(mock_api)

        # Act & Assert
        with self.assertRaises(OpenApiException):
            client.create_wallet()

    def test_create_wallet_generates_idempotency_key_when_none(self):
        # Arrange
        mock_api = Mock()
        mock_api.create_wallet_with_http_info.return_value = Mock(
            raw_data=json.dumps(self._make_wallets_body(self._make_wallet_pair()))
        )
        client = self._make_client(mock_api)

        # Act
        client.create_wallet()

        # Assert
        call_args = mock_api.create_wallet_with_http_info.call_args
        request = call_args[0][0]
        self.assertIsNotNone(request.idempotency_key)

    def test_get_wallet_live_returns_result(self):
        # Arrange
        wallet_id = "4c2ba4e6-2a5a-4bfa-9f7a-7a3b6c1c8f01"
        mock_api = self._make_sdk_wallets_api(
            {"data": {"wallet": self._make_wallet_payload(id=wallet_id)}}
        )
        client = self._make_client(mock_api)

        # Act
        result = client.get_wallet(wallet_id)

        # Assert
        self.assertEqual(result.wallet_id, wallet_id)
        self.assertEqual(result.address, "0xabc123")
        self.assertEqual(result.state, "LIVE")

    def test_get_wallet_accepts_sca_core_unknown_to_sdk(self):
        # Arrange
        wallet_id = "4c2ba4e6-2a5a-4bfa-9f7a-7a3b6c1c8f01"
        wallet = self._make_wallet_payload(
            id=wallet_id, sca_core="circle_6900_singleowner_v4"
        )
        mock_api = self._make_sdk_wallets_api({"data": {"wallet": wallet}})
        client = self._make_client(mock_api)

        # Act
        result = client.get_wallet(wallet_id)

        # Assert
        self.assertEqual(result.wallet_id, wallet_id)
        self.assertEqual(result.address, "0xabc123")
        self.assertEqual(result.state, "LIVE")

    def test_get_wallet_not_live_returns_result_with_state(self):
        # Arrange
        wallet_id = "4c2ba4e6-2a5a-4bfa-9f7a-7a3b6c1c8f01"
        wallet = self._make_wallet_payload(id=wallet_id, address="", state="FROZEN")
        mock_api = self._make_sdk_wallets_api({"data": {"wallet": wallet}})
        client = self._make_client(mock_api)

        # Act
        result = client.get_wallet(wallet_id)

        # Assert
        self.assertEqual(result.wallet_id, wallet_id)
        self.assertEqual(result.address, "")
        self.assertEqual(result.state, "FROZEN")

    def test_create_transfer_returns_result(self):
        mock_tx_api = Mock()
        tx_instance = Mock()
        tx_instance.id = "transfer-uuid-1"
        tx_instance.state = Mock(value="INITIATED")

        mock_data = Mock()
        mock_data.actual_instance = tx_instance
        mock_tx_api.create_developer_transaction_transfer.return_value = Mock(
            data=mock_data
        )

        client = self._make_client(
            mock_transactions_api=mock_tx_api,
        )
        result = client.create_transfer(
            wallet_id="wallet-1",
            destination_address="0xMultisig",
            token_address="0xRSC",
            blockchain="BASE",
            amount="100.5",
        )

        self.assertEqual(result.transfer_id, "transfer-uuid-1")
        self.assertEqual(result.state, "INITIATED")
        mock_tx_api.create_developer_transaction_transfer.assert_called_once()
        call_args = mock_tx_api.create_developer_transaction_transfer.call_args
        request = call_args[0][0]
        self.assertIsNotNone(request.idempotency_key)

    def test_create_transfer_no_data_raises(self):
        mock_tx_api = Mock()
        mock_tx_api.create_developer_transaction_transfer.return_value = Mock(data=None)

        client = self._make_client(
            mock_transactions_api=mock_tx_api,
        )

        with self.assertRaises(CircleTransferError):
            client.create_transfer(
                wallet_id="wallet-1",
                destination_address="0xMultisig",
                token_address="0xRSC",
                blockchain="BASE",
                amount="50",
            )

    def test_create_transfer_sdk_error_raises(self):
        mock_tx_api = Mock()
        mock_tx_api.create_developer_transaction_transfer.side_effect = RuntimeError(
            "network down"
        )

        client = self._make_client(
            mock_transactions_api=mock_tx_api,
        )

        with self.assertRaises(CircleTransferError):
            client.create_transfer(
                wallet_id="wallet-1",
                destination_address="0xMultisig",
                token_address="0xRSC",
                blockchain="BASE",
                amount="50",
            )

    def test_create_transfer_failed_state_raises(self):
        mock_tx_api = Mock()
        tx_instance = Mock()
        tx_instance.id = "transfer-uuid-3"
        tx_instance.state = Mock(value="FAILED")

        mock_data = Mock()
        mock_data.actual_instance = tx_instance
        mock_tx_api.create_developer_transaction_transfer.return_value = Mock(
            data=mock_data
        )

        client = self._make_client(
            mock_transactions_api=mock_tx_api,
        )

        with self.assertRaises(CircleTransferError):
            client.create_transfer(
                wallet_id="wallet-1",
                destination_address="0xMultisig",
                token_address="0xRSC",
                blockchain="BASE",
                amount="50",
            )

    # ── get_wallet_balance ──

    def test_get_wallet_balance_returns_amount(self):
        mock_api = Mock()
        balance_item = Mock()
        balance_item.amount = "1234.567"
        mock_api.list_wallet_balance.return_value = Mock(
            data=Mock(token_balances=[balance_item])
        )

        client = self._make_client(mock_api)
        result = client.get_wallet_balance("wallet-1", "0xRSC")

        self.assertEqual(result, Decimal("1234.567"))
        mock_api.list_wallet_balance.assert_called_once_with(
            id="wallet-1", token_address="0xRSC"
        )

    def test_get_wallet_balance_empty_list_returns_zero(self):
        mock_api = Mock()
        mock_api.list_wallet_balance.return_value = Mock(data=Mock(token_balances=[]))

        client = self._make_client(mock_api)
        result = client.get_wallet_balance("wallet-1", "0xRSC")

        self.assertEqual(result, Decimal(0))

    def test_get_wallet_balance_none_list_returns_zero(self):
        mock_api = Mock()
        mock_api.list_wallet_balance.return_value = Mock(data=Mock(token_balances=None))

        client = self._make_client(mock_api)
        result = client.get_wallet_balance("wallet-1", "0xRSC")

        self.assertEqual(result, Decimal(0))

    def test_get_wallet_balance_sdk_error_raises(self):
        mock_api = Mock()
        mock_api.list_wallet_balance.side_effect = OpenApiException("api down")

        client = self._make_client(mock_api)

        with self.assertRaises(CircleBalanceError):
            client.get_wallet_balance("wallet-1", "0xRSC")

    def test_get_wallet_balance_unexpected_error_raises(self):
        mock_api = Mock()
        mock_api.list_wallet_balance.side_effect = RuntimeError("unexpected")

        client = self._make_client(mock_api)

        with self.assertRaises(CircleBalanceError):
            client.get_wallet_balance("wallet-1", "0xRSC")
