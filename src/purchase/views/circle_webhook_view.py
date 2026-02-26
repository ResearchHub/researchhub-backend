import json
import logging
import time
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.circle.service import COMPLETED_STATES, FAILED_STATES
from purchase.circle.webhook import is_rsc_token, verify_webhook_signature
from purchase.models import Wallet
from purchase.tasks import sweep_deposit_to_multisig
from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Deposit

logger = logging.getLogger(__name__)

# Map Circle blockchain identifiers to our Deposit.network choices
BLOCKCHAIN_TO_NETWORK = {
    "ETH": "ETHEREUM",
    "ETH-SEPOLIA": "ETHEREUM",
    "BASE": "BASE",
    "BASE-SEPOLIA": "BASE",
}


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
        # Only process completed transfers.
        # Circle uses "COMPLETED" for inbound and "COMPLETE" for outbound;
        # accept both defensively.
        state = notification.get("state")
        if state not in COMPLETED_STATES:
            logger.info(
                "Ignoring Circle inbound transfer in state: %s (id=%s)",
                state,
                notification.get("id"),
            )
            return Response(status=status.HTTP_200_OK)

        try:
            self._process_inbound_transfer(payload, notification)
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
                    sweep_status=Deposit.SWEEP_COMPLETE,
                )
                .update(sweep_status=Deposit.SWEEP_COMPLETE)
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

    def _process_inbound_transfer(self, payload, notification):
        notification_id = payload["notificationId"]
        circle_transaction_id = notification["id"]
        wallet_id = notification["walletId"]
        blockchain = notification.get("blockchain", "")
        source_address = notification.get("sourceAddress", "")
        tx_hash = notification.get("txHash", "")
        token_id = notification.get("tokenId")
        amounts = notification.get("amounts", [])

        if not is_rsc_token(token_id, blockchain):
            logger.error(
                "Unsupported Circle token_id=%r for blockchain=%r notification_id=%s",
                token_id,
                blockchain,
                notification_id,
            )
            return

        # Validate deposit amount
        deposit_amount = amounts[0] if amounts else None
        if not deposit_amount:
            logger.error("No amounts in Circle notification %s", notification_id)
            return

        try:
            parsed_amount = Decimal(deposit_amount)
        except InvalidOperation:
            logger.error(
                "Invalid deposit amount %r in notification %s",
                deposit_amount,
                notification_id,
            )
            return

        if parsed_amount <= 0:
            logger.error(
                "Non-positive deposit amount %s in notification %s",
                deposit_amount,
                notification_id,
            )
            return

        network = BLOCKCHAIN_TO_NETWORK.get(blockchain)
        if network is None:
            logger.error(
                "Unknown Circle blockchain %r for wallet_id=%s notification_id=%s",
                blockchain,
                wallet_id,
                notification_id,
            )
            return

        # Look up the wallet (and user) by the chain-specific wallet ID.
        try:
            wallet = Wallet.get_by_circle_wallet_id(wallet_id, network=network)
        except Wallet.DoesNotExist:
            logger.warning(
                "Circle webhook for unknown wallet_id=%s, notification_id=%s",
                wallet_id,
                notification_id,
            )
            return

        user = wallet.user

        with transaction.atomic():
            deposit, created = Deposit.objects.get_or_create(
                circle_transaction_id=circle_transaction_id,
                defaults={
                    "user": user,
                    "amount": deposit_amount,
                    "network": network,
                    "from_address": source_address,
                    "transaction_hash": tx_hash,
                    "sweep_status": Deposit.SWEEP_PENDING,
                },
            )

            if not created:
                logger.info(
                    "Duplicate Circle transaction %s (notification_id=%s), skipping credit",
                    circle_transaction_id,
                    notification_id,
                )
            else:
                deposit.set_paid()

                distribution = Dist("DEPOSIT", deposit_amount, give_rep=False)
                distributor = Distributor(
                    distribution, user, deposit, time.time(), user
                )
                distributor.distribute()

        if created:
            logger.info(
                "Circle deposit credited: user=%s amount=%s blockchain=%s "
                "network=%s circle_transaction_id=%s notification_id=%s",
                user.id,
                deposit_amount,
                blockchain,
                network,
                circle_transaction_id,
                notification_id,
            )

        sweep_wallet_id = wallet.get_circle_wallet_id_for_network(network)
        if not sweep_wallet_id:
            logger.error(
                "No Circle wallet ID for network=%s wallet_pk=%s "
                "circle_transaction_id=%s — skipping sweep",
                network,
                wallet.pk,
                circle_transaction_id,
            )
            return

        def _dispatch_sweep(
            cw=sweep_wallet_id,
            amt=deposit_amount,
            net=network,
            ref=circle_transaction_id,
        ):
            sweep_deposit_to_multisig.delay(cw, amt, net, ref)

        transaction.on_commit(_dispatch_sweep)
