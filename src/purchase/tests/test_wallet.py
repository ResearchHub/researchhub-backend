from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_defunct
from rest_framework.test import APITestCase
from web3 import Web3

from purchase.related_models.wallet_model import Wallet
from purchase.views.wallet_view import VERIFICATION_MESSAGE_TEMPLATE
from user.tests.helpers import create_random_authenticated_user


class WalletTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("wallet_user")
        self.account = Account.create()
        self.address = self.account.address

    def _request_verification(self, address=None):
        self.client.force_authenticate(self.user)
        return self.client.post(
            "/api/wallet/request_verification/",
            {"address": address or self.address},
        )

    def _build_message(self, address, nonce):
        return VERIFICATION_MESSAGE_TEMPLATE.format(address=address, nonce=nonce)

    def _sign_message(self, message, account=None):
        account = account or self.account
        signable = encode_defunct(text=message)
        signed = account.sign_message(signable)
        return signed.signature.hex()

    # ---- request_verification ----

    def test_request_verification(self):
        response = self._request_verification()
        self.assertEqual(response.status_code, 200)
        self.assertIn("message", response.data)
        self.assertIn("nonce", response.data)
        self.assertIn(self.address, response.data["message"])

        confirmation = Wallet.objects.get(id=response.data["id"])
        self.assertEqual(confirmation.status, Wallet.PENDING)
        self.assertEqual(confirmation.user, self.user)

    def test_request_verification_invalid_address(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/wallet/request_verification/",
            {"address": "not-an-address"},
        )
        self.assertEqual(response.status_code, 400)

    def test_request_verification_replaces_pending(self):
        """A new request should delete previous PENDING entries."""
        self._request_verification()
        self.assertEqual(
            Wallet.objects.filter(user=self.user, status=Wallet.PENDING).count(),
            1,
        )

        self._request_verification()
        self.assertEqual(
            Wallet.objects.filter(user=self.user, status=Wallet.PENDING).count(),
            1,
        )

    # ---- confirm (EOA) ----

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_confirm_eoa_wallet(self, mock_verify):
        mock_verify.return_value = True
        response = self._request_verification()
        nonce = response.data["nonce"]
        message = self._build_message(self.address, nonce)
        signature = self._sign_message(message)

        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/wallet/confirm/",
            {"address": self.address, "signature": signature},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Wallet.CONFIRMED)

        confirmation = Wallet.objects.get(
            user=self.user,
            address=Web3.to_checksum_address(self.address),
            status=Wallet.CONFIRMED,
        )
        self.assertIsNotNone(confirmation.confirmed_at)

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_confirm_rejects_wrong_signature(self, mock_verify):
        mock_verify.return_value = False
        self._request_verification()

        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/wallet/confirm/",
            {"address": self.address, "signature": "0xbadsig"},
        )
        self.assertEqual(response.status_code, 400)

        # Still pending
        confirmation = Wallet.objects.get(
            user=self.user,
            address=Web3.to_checksum_address(self.address),
            status=Wallet.PENDING,
        )
        self.assertEqual(confirmation.status, Wallet.PENDING)

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_confirm_rejects_expired_nonce(self, mock_verify):
        mock_verify.return_value = True
        response = self._request_verification()

        # Manually expire the nonce
        confirmation = Wallet.objects.get(id=response.data["id"])
        Wallet.objects.filter(id=confirmation.id).update(
            created_date=timezone.now() - timedelta(minutes=11)
        )

        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/wallet/confirm/",
            {
                "address": self.address,
                "signature": "0xanysig",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("expired", response.data["error"].lower())

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_confirm_rejects_duplicate_address(self, mock_verify):
        """A second user cannot confirm an already-confirmed address."""
        mock_verify.return_value = True

        # First user confirms
        self._request_verification()
        self.client.force_authenticate(self.user)
        self.client.post(
            "/api/wallet/confirm/",
            {"address": self.address, "signature": "0xvalid"},
        )

        # Second user tries same address
        user2 = create_random_authenticated_user("wallet_user2")
        self.client.force_authenticate(user2)
        self.client.post(
            "/api/wallet/request_verification/",
            {"address": self.address},
        )
        response = self.client.post(
            "/api/wallet/confirm/",
            {"address": self.address, "signature": "0xvalid"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already confirmed", response.data["error"].lower())

    # ---- list ----

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_list_confirmed_wallets(self, mock_verify):
        mock_verify.return_value = True

        # Create a PENDING and a CONFIRMED wallet
        self._request_verification()
        self.client.force_authenticate(self.user)
        self.client.post(
            "/api/wallet/confirm/",
            {"address": self.address, "signature": "0xvalid"},
        )

        # Create another pending one (different address)
        other_account = Account.create()
        self._request_verification(address=other_account.address)

        response = self.client.get("/api/wallet/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["address"], Web3.to_checksum_address(self.address)
        )

    # ---- destroy ----

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_delete_confirmed_wallet(self, mock_verify):
        mock_verify.return_value = True
        self._request_verification()
        self.client.force_authenticate(self.user)
        self.client.post(
            "/api/wallet/confirm/",
            {"address": self.address, "signature": "0xvalid"},
        )

        confirmation = Wallet.objects.get(
            user=self.user,
            address=Web3.to_checksum_address(self.address),
            status=Wallet.CONFIRMED,
        )

        response = self.client.delete(f"/api/wallet/{confirmation.id}/")
        self.assertEqual(response.status_code, 204)

        # Verify it's gone
        response = self.client.get("/api/wallet/")
        self.assertEqual(len(response.data), 0)

    def test_delete_other_users_wallet_returns_404(self):
        """A user cannot delete another user's confirmed wallet."""
        Wallet.objects.create(
            user=self.user,
            address=Web3.to_checksum_address(self.address),
            nonce="test",
            status=Wallet.CONFIRMED,
            confirmed_at=timezone.now(),
        )
        confirmation = Wallet.objects.get(user=self.user)

        user2 = create_random_authenticated_user("wallet_user3")
        self.client.force_authenticate(user2)
        response = self.client.delete(f"/api/wallet/{confirmation.id}/")
        self.assertEqual(response.status_code, 404)

    # ---- smart wallet (EIP-1271) ----

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_confirm_smart_wallet(self, mock_verify):
        """Smart wallet verification via mocked EIP-1271."""
        mock_verify.return_value = True

        response = self._request_verification()
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/wallet/confirm/",
            {
                "address": self.address,
                "signature": "0xsmartwalletvalid",
                "network": "BASE",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], Wallet.CONFIRMED)

    @patch("purchase.views.wallet_view.verify_wallet_signature")
    def test_smart_wallet_invalid_signature(self, mock_verify):
        """Smart wallet with invalid EIP-1271 signature returns 400."""
        mock_verify.return_value = False

        self._request_verification()
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/wallet/confirm/",
            {
                "address": self.address,
                "signature": "0xsmartwalletinvalid",
                "network": "BASE",
            },
        )
        self.assertEqual(response.status_code, 400)


class VerifyEoaSignatureTests(APITestCase):
    """Test the actual EOA signature verification logic (no mocking)."""

    def test_verify_eoa_signature_valid(self):
        from ethereum.lib import verify_eoa_signature

        account = Account.create()
        message = "test message"
        signable = encode_defunct(text=message)
        signed = account.sign_message(signable)

        self.assertTrue(
            verify_eoa_signature(account.address, message, signed.signature.hex())
        )

    def test_verify_eoa_signature_wrong_signer(self):
        from ethereum.lib import verify_eoa_signature

        account1 = Account.create()
        account2 = Account.create()
        message = "test message"
        signable = encode_defunct(text=message)
        signed = account1.sign_message(signable)

        self.assertFalse(
            verify_eoa_signature(account2.address, message, signed.signature.hex())
        )
