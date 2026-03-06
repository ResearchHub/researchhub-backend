import json
import logging
from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.circle.service import (
    BLOCKCHAIN_TO_NETWORK,
    COMPLETED_STATES,
    FAILED_STATES,
    PENDING_DEPOSIT_STATES,
    is_rsc_token,
    process_circle_deposit,
    upsert_pending_circle_deposit,
)
from purchase.circle.webhook import verify_webhook_signature
from purchase.models import Wallet
from reputation.models import Deposit

logger = logging.getLogger(__name__)


class CircleWebhookView(APIView):
    """
    Receives webhook notifications from Circle for transfers.

    Handles two notification types:
    - ``transactions.inbound``: User deposited RSC to their Circle wallet.
      We credit the user's in-app balance and record a Deposit.
    - ``transactions.outbound``: A sweep transfer we initiated has settled
      (or failed). We update the Deposit's sweep_status accordingly.

    POST /webhooks/circle/
    """

    permission_classes = [AllowAny]

    def head(self, request, *args, **kwargs):
        """Circle requires the webhook endpoint to accept HEAD requests."""
        return Response(status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        # --- Signature verification ---
        signature = request.headers.get("X-Circle-Signature")
        key_id = request.headers.get("X-Circle-Key-Id")

        if not signature or not key_id:
            return Response(
                {"message": "Missing signature headers"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        body = request.body

        try:
            valid = verify_webhook_signature(body, signature, key_id)
        except Exception:
            logger.warning(
                "Transient failure verifying Circle webhook signature",
                exc_info=True,
            )
            return Response(
                {"message": "Signature verification temporarily unavailable"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not valid:
            return Response(
                {"message": "Invalid signature"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # --- Parse payload ---
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return Response(
                {"message": "Invalid payload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        notification_type = payload.get("notificationType")
        notification = payload.get("notification", {})

        if notification_type == "transactions.inbound":
            return self._handle_inbound(payload, notification)
        elif notification_type == "transactions.outbound":
            return self._handle_outbound(payload, notification)
        else:
            logger.info("Ignoring Circle notification type: %s", notification_type)
            return Response(status=status.HTTP_200_OK)

    def _handle_inbound(self, payload, notification):
        state = notification.get("state")

        if state in COMPLETED_STATES:
            handler = self._process_inbound_transfer
        elif state in PENDING_DEPOSIT_STATES:
            handler = self._create_pending_deposit
        elif state in FAILED_STATES:
            handler = self._fail_deposit
        else:
            logger.info(
                "Ignoring Circle inbound transfer in state: %s (id=%s)",
                state,
                notification.get("id"),
            )
            return Response(status=status.HTTP_200_OK)

        try:
            handler(payload, notification)
        except Exception:
            logger.exception(
                "Error processing Circle inbound transfer notification_id=%s",
                payload.get("notificationId"),
            )
            return Response(
                {"message": "Error processing notification"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"message": "Webhook successfully processed"},
            status=status.HTTP_200_OK,
        )

    def _handle_outbound(self, payload, notification):
        state = notification.get("state", "")
        transaction_id = notification.get("id")

        if not transaction_id:
            logger.warning(
                "Outbound notification missing transaction id, notification_id=%s",
                payload.get("notificationId"),
            )
            return Response(status=status.HTTP_200_OK)

        if state in COMPLETED_STATES:
            updated = (
                Deposit.objects.filter(
                    sweep_transfer_id=transaction_id,
                )
                .exclude(
                    sweep_status=Deposit.SWEEP_COMPLETED,
                )
                .update(sweep_status=Deposit.SWEEP_COMPLETED)
            )

            if updated:
                logger.info(
                    "Sweep marked COMPLETE: transfer_id=%s notification_id=%s",
                    transaction_id,
                    payload.get("notificationId"),
                )
        elif state in FAILED_STATES:
            updated = (
                Deposit.objects.filter(
                    sweep_transfer_id=transaction_id,
                )
                .exclude(
                    sweep_status=Deposit.SWEEP_FAILED,
                )
                .update(sweep_status=Deposit.SWEEP_FAILED)
            )

            if updated:
                logger.warning(
                    "Sweep marked FAILED via outbound webhook: transfer_id=%s "
                    "state=%s notification_id=%s",
                    transaction_id,
                    state,
                    payload.get("notificationId"),
                )
        else:
            logger.info(
                "Ignoring Circle outbound transfer in state: %s (id=%s)",
                state,
                transaction_id,
            )

        return Response(status=status.HTTP_200_OK)

    def _validate_inbound_notification(self, payload, notification):
        """
        Validate and extract fields from an inbound Circle notification.

        Returns a dict with validated fields, or ``None`` if the notification
        is invalid and should be silently dropped.
        """
        notification_id = payload["notificationId"]
        wallet_id = notification["walletId"]
        blockchain = notification.get("blockchain", "")
        token_id = notification.get("tokenId")
        amounts = notification.get("amounts", [])

        if not is_rsc_token(token_id, blockchain):
            logger.error(
                "Unsupported Circle token_id=%r for blockchain=%r notification_id=%s",
                token_id,
                blockchain,
                notification_id,
            )
            return None

        deposit_amount = amounts[0] if amounts else None
        if not deposit_amount:
            logger.error("No amounts in Circle notification %s", notification_id)
            return None

        try:
            parsed_amount = Decimal(deposit_amount)
        except InvalidOperation:
            logger.error(
                "Invalid deposit amount %r in notification %s",
                deposit_amount,
                notification_id,
            )
            return None

        if parsed_amount <= 0:
            logger.error(
                "Non-positive deposit amount %s in notification %s",
                deposit_amount,
                notification_id,
            )
            return None

        network = BLOCKCHAIN_TO_NETWORK.get(blockchain)
        if network is None:
            logger.error(
                "Unknown Circle blockchain %r for wallet_id=%s notification_id=%s",
                blockchain,
                wallet_id,
                notification_id,
            )
            return None

        try:
            wallet = Wallet.get_by_circle_wallet_id(wallet_id, network=network)
        except Wallet.DoesNotExist:
            logger.warning(
                "Circle webhook for unknown wallet_id=%s, notification_id=%s",
                wallet_id,
                notification_id,
            )
            return None

        return {
            "circle_transaction_id": notification["id"],
            "wallet": wallet,
            "amount": deposit_amount,
            "network": network,
            "from_address": notification.get("sourceAddress", ""),
            "transaction_hash": notification.get("txHash", ""),
        }

    def _create_pending_deposit(self, payload, notification):
        """Create or update a pending deposit for an in-progress Circle transaction."""
        validated = self._validate_inbound_notification(payload, notification)
        if validated is None:
            return

        upsert_pending_circle_deposit(
            circle_status=notification["state"],
            **validated,
        )

    def _fail_deposit(self, payload, notification):
        """Mark an existing pending deposit as failed."""
        circle_transaction_id = notification.get("id")
        if not circle_transaction_id:
            return

        updated = (
            Deposit.objects.filter(
                circle_transaction_id=circle_transaction_id,
            )
            .exclude(
                paid_status=Deposit.PAID,
            )
            .update(
                circle_status=Deposit.CIRCLE_FAILED,
                paid_status=Deposit.FAILED,
            )
        )

        if updated:
            logger.warning(
                "Deposit marked FAILED via inbound webhook: "
                "circle_transaction_id=%s state=%s notification_id=%s",
                circle_transaction_id,
                notification.get("state"),
                payload.get("notificationId"),
            )
        else:
            logger.info(
                "No pending deposit found to fail: circle_transaction_id=%s "
                "notification_id=%s",
                circle_transaction_id,
                payload.get("notificationId"),
            )

    def _process_inbound_transfer(self, payload, notification):
        validated = self._validate_inbound_notification(payload, notification)
        if validated is None:
            return

        process_circle_deposit(**validated)
