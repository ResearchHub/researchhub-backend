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
    transaction_id="tx-001",
    wallet_id="circle-wallet-base-abc",
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
            "id": transaction_id,
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
            circle_base_wallet_id="circle-wallet-base-abc",
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
        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.user, self.user)
        self.assertEqual(deposit.amount, "100")
        self.assertEqual(deposit.network, "BASE")
        self.assertEqual(deposit.paid_status, "PAID")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_COMPLETED)
        self.assertEqual(deposit.sweep_status, Deposit.SWEEP_PENDING)

        # Balance was credited (via Distributor)
        from purchase.models import Balance

        balance = Balance.objects.filter(user=self.user).first()
        self.assertIsNotNone(balance)
        self.assertEqual(balance.amount, "100")

        # User was auto-opted into staking
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staking_opted_in)
        self.assertIsNotNone(self.user.staking_opted_in_date)

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
            Deposit.objects.filter(circle_transaction_id="tx-001").count(), 1
        )

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_unknown_notification_type_returns_200_ignored(self, _mock_verify):
        payload = _make_payload(notification_type="transactions.unknown")
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
        payload = _make_payload(wallet_id="circle-wallet-abc", blockchain="ETH")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
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

    @patch("purchase.views.circle_webhook_view.dispatch_sweep")
    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature",
        return_value=True,
    )
    def test_sweep_task_dispatched_after_credit(self, _mock_verify, mock_dispatch):
        """After crediting balance, sweep is dispatched with correct args."""
        payload = _make_payload()
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_dispatch.assert_called_once_with(self.wallet, "100", "BASE", "tx-001")

    @patch("purchase.views.circle_webhook_view.dispatch_sweep")
    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature",
        return_value=True,
    )
    def test_sweep_not_dispatched_on_duplicate(self, _mock_verify, mock_dispatch):
        """Duplicate notification should not re-dispatch sweep."""
        payload = _make_payload()
        with self.captureOnCommitCallbacks(execute=True):
            self._post(payload)
        mock_dispatch.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            self._post(payload)
        mock_dispatch.assert_not_called()

    @patch("purchase.views.circle_webhook_view.dispatch_sweep")
    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature",
        return_value=True,
    )
    def test_sweep_uses_eth_wallet_id_for_eth_deposit(
        self, _mock_verify, mock_dispatch
    ):
        """ETH deposit uses circle_wallet_id (ETH) for sweep."""
        payload = _make_payload(wallet_id="circle-wallet-abc", blockchain="ETH")
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_dispatch.assert_called_once_with(self.wallet, "100", "ETHEREUM", "tx-001")

    @patch("purchase.views.circle_webhook_view.dispatch_sweep")
    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature",
        return_value=True,
    )
    def test_base_deposit_found_by_base_wallet_id(self, _mock_verify, mock_dispatch):
        """Base chain deposit is found via circle_base_wallet_id."""
        payload = _make_payload(wallet_id="circle-wallet-base-abc", blockchain="BASE")
        with self.captureOnCommitCallbacks(execute=True):
            response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.network, "BASE")
        mock_dispatch.assert_called_once_with(self.wallet, "100", "BASE", "tx-001")

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_initiated_state_creates_pending_deposit(self, _mock_verify):
        """INITIATED webhook creates a deposit with pending paid_status."""
        payload = _make_payload(state="INITIATED")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.user, self.user)
        self.assertEqual(deposit.amount, "100")
        self.assertEqual(deposit.network, "BASE")
        self.assertEqual(deposit.paid_status, "PENDING")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_INITIATED)
        self.assertEqual(deposit.sweep_status, "")

        # No balance credited yet
        from purchase.models import Balance

        self.assertFalse(Balance.objects.filter(user=self.user).exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_confirmed_state_creates_pending_deposit(self, _mock_verify):
        """CONFIRMED webhook creates a deposit with pending paid_status."""
        payload = _make_payload(state="CONFIRMED")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.paid_status, "PENDING")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_CONFIRMED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_initiated_then_confirmed_advances_circle_status(self, _mock_verify):
        """CONFIRMED webhook advances an existing INITIATED deposit."""
        self._post(_make_payload(state="INITIATED"))
        self._post(_make_payload(state="CONFIRMED"))

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_CONFIRMED)
        self.assertEqual(deposit.paid_status, "PENDING")

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_confirmed_does_not_regress_to_initiated(self, _mock_verify):
        """INITIATED webhook does not regress an already-CONFIRMED deposit."""
        self._post(_make_payload(state="CONFIRMED"))
        self._post(_make_payload(state="INITIATED"))

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_CONFIRMED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_failed_deposit_not_regressed_by_pending_webhook(self, _mock_verify):
        """INITIATED/CONFIRMED webhook does not regress a FAILED deposit."""
        self._post(_make_payload(state="INITIATED"))
        self._post(_make_payload(state="FAILED"))

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_FAILED)

        # Late INITIATED webhook should not overwrite FAILED
        self._post(_make_payload(state="INITIATED"))
        deposit.refresh_from_db()
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_FAILED)
        self.assertEqual(deposit.paid_status, "FAILED")

        # Late CONFIRMED webhook should not overwrite FAILED either
        self._post(_make_payload(state="CONFIRMED"))
        deposit.refresh_from_db()
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_FAILED)
        self.assertEqual(deposit.paid_status, "FAILED")

    @patch("purchase.views.circle_webhook_view.dispatch_sweep")
    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_pending_deposit_promoted_to_paid_on_completed(
        self, _mock_verify, mock_dispatch
    ):
        """COMPLETED webhook promotes a pending deposit to PAID and credits user."""
        # First, create pending deposit via INITIATED webhook
        self._post(_make_payload(state="INITIATED"))

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.paid_status, "PENDING")

        # Then, COMPLETED webhook should credit the user
        with self.captureOnCommitCallbacks(execute=True):
            self._post(_make_payload(state="COMPLETED"))

        deposit.refresh_from_db()
        self.assertEqual(deposit.paid_status, "PAID")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_COMPLETED)
        self.assertEqual(deposit.sweep_status, Deposit.SWEEP_PENDING)
        self.assertIsNotNone(deposit.paid_date)

        # Balance was credited
        from purchase.models import Balance

        balance = Balance.objects.filter(user=self.user).first()
        self.assertIsNotNone(balance)
        self.assertEqual(balance.amount, "100")

        # User was auto-opted into staking
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_staking_opted_in)
        self.assertIsNotNone(self.user.staking_opted_in_date)

        # Sweep was dispatched
        mock_dispatch.assert_called_once()

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_failed_state_marks_pending_deposit_failed(self, _mock_verify):
        """FAILED webhook marks a pending deposit as failed."""
        self._post(_make_payload(state="INITIATED"))

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.paid_status, "PENDING")

        response = self._post(_make_payload(state="FAILED"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit.refresh_from_db()
        self.assertEqual(deposit.paid_status, "FAILED")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_FAILED)

        # No balance credited
        from purchase.models import Balance

        self.assertFalse(Balance.objects.filter(user=self.user).exists())

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_cancelled_state_marks_pending_deposit_failed(self, _mock_verify):
        """CANCELLED webhook marks a pending deposit as failed."""
        self._post(_make_payload(state="CONFIRMED"))

        response = self._post(_make_payload(state="CANCELLED"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.paid_status, "FAILED")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_FAILED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_denied_state_marks_pending_deposit_failed(self, _mock_verify):
        """DENIED webhook marks a pending deposit as failed."""
        self._post(_make_payload(state="INITIATED"))

        response = self._post(_make_payload(state="DENIED"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.paid_status, "FAILED")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_FAILED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_failed_state_does_not_revert_paid_deposit(self, _mock_verify):
        """FAILED webhook does not revert an already-paid deposit."""
        # Create a paid deposit
        self._post(_make_payload(state="COMPLETED"))

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.paid_status, "PAID")

        # Late FAILED webhook should not affect it
        response = self._post(_make_payload(state="FAILED"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit.refresh_from_db()
        self.assertEqual(deposit.paid_status, "PAID")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_COMPLETED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_failed_state_no_existing_deposit_returns_200(self, _mock_verify):
        """FAILED webhook with no existing deposit returns 200 gracefully."""
        response = self._post(_make_payload(state="FAILED"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Deposit.objects.exists())

    @patch("purchase.views.circle_webhook_view.dispatch_sweep")
    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_full_lifecycle_initiated_confirmed_completed(
        self, _mock_verify, _mock_dispatch
    ):
        """Full lifecycle: INITIATED -> CONFIRMED -> COMPLETED credits user once."""
        self._post(_make_payload(state="INITIATED"))
        self._post(_make_payload(state="CONFIRMED"))

        with self.captureOnCommitCallbacks(execute=True):
            self._post(_make_payload(state="COMPLETED"))

        deposit = Deposit.objects.get(circle_transaction_id="tx-001")
        self.assertEqual(deposit.paid_status, "PAID")
        self.assertEqual(deposit.circle_status, Deposit.CIRCLE_COMPLETED)

        # Only one deposit and one balance entry
        self.assertEqual(Deposit.objects.count(), 1)

        from purchase.models import Balance

        self.assertEqual(Balance.objects.filter(user=self.user).count(), 1)


def _make_outbound_payload(
    notification_id="notif-out-001",
    transaction_id="sweep-tx-001",
    state="COMPLETE",
    wallet_id="circle-wallet-abc",
):
    """Build a Circle outbound transaction webhook payload."""
    return {
        "subscriptionId": "sub-001",
        "notificationId": notification_id,
        "notificationType": "transactions.outbound",
        "notification": {
            "id": transaction_id,
            "blockchain": "BASE",
            "walletId": wallet_id,
            "state": state,
            "transactionType": "OUTBOUND",
            "createDate": "2026-01-01T00:00:00Z",
            "updateDate": "2026-01-01T00:01:00Z",
        },
        "timestamp": "2026-01-01T00:01:00.000Z",
        "version": 2,
    }


class TestCircleOutboundWebhook(TestCase):
    def setUp(self):
        self.url = reverse("circle_webhook")
        self.user = User.objects.create_user(username="sweeper")
        self.wallet = Wallet.objects.create(
            user=self.user,
            circle_wallet_id="circle-wallet-abc",
            circle_base_wallet_id="circle-wallet-base-abc",
            wallet_type=Wallet.WALLET_TYPE_CIRCLE,
            address="0xUserAddress",
        )

    def _post(self, payload, sig="valid-sig", key_id="key-001"):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            headers={
                "X-Circle-Signature": sig,
                "X-Circle-Key-Id": key_id,
            },
        )

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_outbound_complete_marks_sweep_complete(self, _mock_verify):
        deposit = Deposit.objects.create(
            user=self.user,
            amount="100",
            network="BASE",
            from_address="",
            circle_transaction_id="notif-inbound",
            sweep_status=Deposit.SWEEP_INITIATED,
            sweep_transfer_id="sweep-tx-001",
        )

        payload = _make_outbound_payload(state="COMPLETE")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit.refresh_from_db()
        self.assertEqual(deposit.sweep_status, Deposit.SWEEP_COMPLETED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_outbound_failed_marks_sweep_failed(self, _mock_verify):
        deposit = Deposit.objects.create(
            user=self.user,
            amount="100",
            network="BASE",
            from_address="",
            circle_transaction_id="notif-inbound",
            sweep_status=Deposit.SWEEP_INITIATED,
            sweep_transfer_id="sweep-tx-001",
        )

        payload = _make_outbound_payload(state="FAILED")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit.refresh_from_db()
        self.assertEqual(deposit.sweep_status, Deposit.SWEEP_FAILED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_outbound_cancelled_marks_sweep_failed(self, _mock_verify):
        deposit = Deposit.objects.create(
            user=self.user,
            amount="100",
            network="BASE",
            from_address="",
            circle_transaction_id="notif-inbound",
            sweep_status=Deposit.SWEEP_INITIATED,
            sweep_transfer_id="sweep-tx-001",
        )

        payload = _make_outbound_payload(state="CANCELLED")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit.refresh_from_db()
        self.assertEqual(deposit.sweep_status, Deposit.SWEEP_FAILED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_outbound_pending_state_ignored(self, _mock_verify):
        deposit = Deposit.objects.create(
            user=self.user,
            amount="100",
            network="BASE",
            from_address="",
            circle_transaction_id="notif-inbound",
            sweep_status=Deposit.SWEEP_INITIATED,
            sweep_transfer_id="sweep-tx-001",
        )

        payload = _make_outbound_payload(state="SENT")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        deposit.refresh_from_db()
        self.assertEqual(deposit.sweep_status, Deposit.SWEEP_INITIATED)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_outbound_unknown_transfer_id_returns_200(self, _mock_verify):
        """Outbound notification for a transfer we don't track is silently ignored."""
        payload = _make_outbound_payload(transaction_id="unknown-tx")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "purchase.views.circle_webhook_view.verify_webhook_signature", return_value=True
    )
    def test_outbound_idempotent_on_already_complete(self, _mock_verify):
        """Duplicate outbound COMPLETE notification doesn't error."""
        Deposit.objects.create(
            user=self.user,
            amount="100",
            network="BASE",
            from_address="",
            circle_transaction_id="notif-inbound",
            sweep_status=Deposit.SWEEP_COMPLETED,
            sweep_transfer_id="sweep-tx-001",
        )

        payload = _make_outbound_payload(state="COMPLETE")
        response = self._post(payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
