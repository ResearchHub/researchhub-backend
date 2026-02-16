from unittest.mock import Mock, patch

from django.test import TestCase

from purchase.circle.client import (
    CircleWalletClient,
    CircleWalletCreationError,
    CircleWalletNotReadyError,
)


class TestCircleWalletClient(TestCase):
    """Tests for CircleWalletClient."""

    def _make_client(self, mock_wallets_api):
        """Create a CircleWalletClient with a mocked WalletsApi."""
        client = CircleWalletClient.__new__(CircleWalletClient)
        client.wallets_api = mock_wallets_api
        return client

    def _make_wallet_instance(self, **kwargs):
        """Create a mock wallet actual_instance."""
        wallet = Mock()
        wallet.id = kwargs.get("id", "wallet-uuid-1")
        wallet.address = kwargs.get("address", "0xABC123")
        wallet.state = kwargs.get("state", Mock(value="LIVE"))
        return wallet

    def test_create_wallet_returns_wallet_id(self):
        mock_api = Mock()
        wallet_instance = self._make_wallet_instance(id="circle-wallet-uuid-1")
        wallet_wrapper = Mock()
        wallet_wrapper.actual_instance = wallet_instance

        mock_api.create_wallet.return_value = Mock(data=Mock(wallets=[wallet_wrapper]))

        client = self._make_client(mock_api)
        wallet_id = client.create_wallet(idempotency_key="test-key-1")

        self.assertEqual(wallet_id, "circle-wallet-uuid-1")
        mock_api.create_wallet.assert_called_once()

    def test_create_wallet_empty_response_raises(self):
        mock_api = Mock()
        mock_api.create_wallet.return_value = Mock(data=Mock(wallets=[]))

        client = self._make_client(mock_api)

        with self.assertRaises(CircleWalletCreationError):
            client.create_wallet()

    def test_create_wallet_generates_idempotency_key_when_none(self):
        mock_api = Mock()
        wallet_instance = self._make_wallet_instance()
        wallet_wrapper = Mock()
        wallet_wrapper.actual_instance = wallet_instance
        mock_api.create_wallet.return_value = Mock(data=Mock(wallets=[wallet_wrapper]))

        client = self._make_client(mock_api)
        client.create_wallet()

        # Verify create_wallet was called (idempotency key auto-generated)
        call_args = mock_api.create_wallet.call_args
        request = call_args[0][0]
        self.assertIsNotNone(request.idempotency_key)

    def test_get_wallet_live_returns_result(self):
        mock_api = Mock()
        live_state = Mock(value="LIVE")
        # WalletState.LIVE comparison
        from circle.web3.developer_controlled_wallets.models import WalletState

        wallet_instance = Mock()
        wallet_instance.id = "wallet-1"
        wallet_instance.address = "0xabc123"
        wallet_instance.state = WalletState.LIVE

        wallet_wrapper = Mock()
        wallet_wrapper.actual_instance = wallet_instance
        mock_api.get_wallet.return_value = Mock(data=Mock(wallet=wallet_wrapper))

        client = self._make_client(mock_api)
        result = client.get_wallet("wallet-1")

        self.assertEqual(result.wallet_id, "wallet-1")
        self.assertEqual(result.address, "0xabc123")
        self.assertEqual(result.state, "LIVE")

    def test_get_wallet_not_live_raises(self):
        mock_api = Mock()
        from circle.web3.developer_controlled_wallets.models import WalletState

        wallet_instance = Mock()
        wallet_instance.id = "wallet-1"
        wallet_instance.address = ""
        wallet_instance.state = WalletState.FROZEN

        wallet_wrapper = Mock()
        wallet_wrapper.actual_instance = wallet_instance
        mock_api.get_wallet.return_value = Mock(data=Mock(wallet=wallet_wrapper))

        client = self._make_client(mock_api)

        with self.assertRaises(CircleWalletNotReadyError):
            client.get_wallet("wallet-1")
