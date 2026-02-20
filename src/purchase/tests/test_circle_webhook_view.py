import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status

from purchase.models import Wallet
from reputation.models import Deposit

User = get_user_model()


def _make_payload(
    notification_id="notif-001",
    wallet_id="circle-wallet-abc",
    notification_type="transactions.inbound",
    state="COMPLETED",
    blockchain="BASE",
    amounts=None,
):
    """Build a Circle webhook payload dict."""
    if amounts is None:
        amounts = ["100"]
    return {
        "subscriptionId": "sub-001",
        "notificationId": notification_id,
        "notificationType": notification_type,
        "notification": {
            "id": "tx-001",
            "blockchain": blockchain,
            "walletId": wallet_id,
            "tokenId": "token-rsc",
            "destinationAddress": "0xDestination",
            "amounts": amounts,
            "state": state,
            "transactionType": "INBOUND",
            "createDate": "2026-01-01T00:00:00Z",
            "updateDate": "2026-01-01T00:01:00Z",
        },
        "timestamp": "2026-01-01T00:01:00.000Z",
        "version": 2,
    }


class TestCircleWebhookView(TestCase):
    def setUp(self):
        self.url = reverse("circle_webhook")
        self.user = User.objects.create_user(username="depositor")
        self.wallet = Wallet.objects.create(
            user=self.user,
            circle_wallet_id="circle-wallet-abc",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
            address="0xUserAddress",
        )
        token_patcher = patch(
            "purchase.views.circle_webhook_view.is_rsc_token",
            return_value=True,
        )
        self.mock_is_rsc_token = token_patcher.start()
        self.addCleanup(token_patcher.stop)

    def _post(self, payload, sig="valid-sig", key_id="key-001"):
        headers = {}
        if sig is not None:
            headers["X-Circle-Signature"] = sig
        if key_id is not None:
            headers["X-Circle-Key-Id"] = key_id
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
        )

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_valid_inbound_transfer_credits_balance(self, _mock_verify):
        payload = _make_payload()
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Deposit record created
        deposit = Deposit.objects.get(circle_notification_id="notif-001")
        self.assertEqual(deposit.user, self.user)
        self.assertEqual(deposit.amount, "100")
        self.assertEqual(deposit.network, "BASE")
        self.assertEqual(deposit.paid_status, "PAID")

        # Balance was credited (via Distributor)
        from purchase.models import Balance

        balance = Balance.objects.filter(user=self.user).first()
        self.assertIsNotNone(balance)
        self.assertEqual(balance.amount, "100")

    def test_missing_signature_headers_returns_401(self):
        payload = _make_payload()
        response = self._post(payload, sig=None, key_id=None)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature",
        return_value=False,
    )
    def test_invalid_signature_returns_401(self, _mock_verify):
        payload = _make_payload()
        response = self._post(payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_unknown_wallet_returns_200_no_deposit(self, _mock_verify):
        payload = _make_payload(wallet_id="unknown-wallet")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_duplicate_notification_is_idempotent(self, _mock_verify):
        payload = _make_payload()
        response1 = self._post(payload)
        response2 = self._post(payload)

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Only one deposit created
        self.assertEqual(
            Deposit.objects.filter(circle_notification_id="notif-001").count(), 1
        )

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_non_inbound_type_returns_200_ignored(self, _mock_verify):
        payload = _make_payload(notification_type="transactions.outbound")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_non_completed_state_returns_200_ignored(self, _mock_verify):
        payload = _make_payload(state="PENDING")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_eth_blockchain_maps_to_ethereum_network(self, _mock_verify):
        payload = _make_payload(blockchain="ETH")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit = Deposit.objects.get(circle_notification_id="notif-001")
        self.assertEqual(deposit.network, "ETHEREUM")

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_empty_amounts_returns_200_no_deposit(self, _mock_verify):
        payload = _make_payload(amounts=[])
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_invalid_amount_returns_200_no_deposit(self, _mock_verify):
        payload = _make_payload(amounts=["not-a-number"])
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_zero_amount_returns_200_no_deposit(self, _mock_verify):
        payload = _make_payload(amounts=["0"])
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_negative_amount_returns_200_no_deposit(self, _mock_verify):
        payload = _make_payload(amounts=["-50"])
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_unknown_blockchain_returns_200_no_deposit(self, _mock_verify):
        payload = _make_payload(blockchain="SOLANA")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_non_rsc_token_returns_200_no_deposit(self, _mock_verify):
        self.mock_is_rsc_token.return_value = False

        payload = _make_payload()
        payload["notification"]["tokenId"] = "token-not-rsc"
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    def test_head_request_returns_200(self):
        response = self.client.head(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestCircleWebhookNoIPFiltering(TestCase):
    def setUp(self):
        self.url = reverse("circle_webhook")

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_remote_addr_does_not_block_request(self, _mock_verify):
        payload = _make_payload(notification_type="transactions.outbound")
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="1.2.3.4",
            headers={
                "X-Circle-Signature": "sig",
                "X-Circle-Key-Id": "key",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_allowed_ip_header_still_returns_200(self, _mock_verify):
        payload = _make_payload(notification_type="transactions.outbound")
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="54.243.112.156",
            headers={
                "X-Circle-Signature": "sig",
                "X-Circle-Key-Id": "key",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_forwarded_for_header_does_not_block_request(self, _mock_verify):
        payload = _make_payload(notification_type="transactions.outbound")
        response = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="54.243.112.156, 10.0.0.1",
            headers={
                "X-Circle-Signature": "sig",
                "X-Circle-Key-Id": "key",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
