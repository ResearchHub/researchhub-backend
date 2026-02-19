import json
import logging
import time
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from purchase.circle.webhook import verify_webhook_signature
from purchase.models import Wallet
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

# Default Circle webhook source IPs.
# https://developers.circle.com/wallets/webhook-notifications
CIRCLE_WEBHOOK_IPS = frozenset(
    {
        "54.243.112.156",
        "100.24.191.35",
        "54.165.52.248",
        "54.87.106.46",
    }
)


def _get_client_ip(request):
    """Return the originating client IP, respecting X-Forwarded-For."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class CircleWebhookView(APIView):
    """
    Receives webhook notifications from Circle for inbound transfers.

    When a user deposits RSC to their Circle wallet, Circle sends a
    ``transactions.inbound`` notification here. We verify the signature,
    credit the user's in-app balance, and record a Deposit.

    POST /webhooks/circle/
    """

    permission_classes = [AllowAny]
    allowed_ips = CIRCLE_WEBHOOK_IPS

    def head(self, request, *args, **kwargs):
        """Circle requires the webhook endpoint to accept HEAD requests."""
        return Response(status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        # --- IP allowlist ---
        if self.allowed_ips:
            client_ip = _get_client_ip(request)
            if client_ip not in self.allowed_ips:
                logger.warning("Circle webhook from disallowed IP: %s", client_ip)
                return Response(
                    {"message": "Forbidden"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # --- Signature verification ---
        signature = request.headers.get("X-Circle-Signature")
        key_id = request.headers.get("X-Circle-Key-Id")

        if not signature or not key_id:
            return Response(
                {"message": "Missing signature headers"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        body = request.body

        if not verify_webhook_signature(body, signature, key_id):
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
        if notification_type != "transactions.inbound":
            logger.info("Ignoring Circle notification type: %s", notification_type)
            return Response(status=status.HTTP_200_OK)

        notification = payload.get("notification", {})

        # Only process completed transfers.
        # Circle uses "COMPLETED" for inbound and "COMPLETE" for outbound;
        # accept both defensively.
        state = notification.get("state")
        if state not in ("COMPLETED", "COMPLETE"):
            logger.info(
                "Ignoring Circle transfer in state: %s (id=%s)",
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

    def _process_inbound_transfer(self, payload, notification):
        notification_id = payload["notificationId"]
        wallet_id = notification["walletId"]
        blockchain = notification.get("blockchain", "")
        amounts = notification.get("amounts", [])

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

        # Idempotency: skip if we already processed this notification
        if Deposit.objects.filter(circle_notification_id=notification_id).exists():
            logger.info("Duplicate Circle notification %s, skipping", notification_id)
            return

        # Look up the wallet (and user) by Circle wallet ID
        try:
            wallet = Wallet.objects.select_related("user").get(
                circle_wallet_id=wallet_id
            )
        except Wallet.DoesNotExist:
            logger.warning(
                "Circle webhook for unknown wallet_id=%s, notification_id=%s",
                wallet_id,
                notification_id,
            )
            return

        user = wallet.user
        network = BLOCKCHAIN_TO_NETWORK.get(blockchain)

        if network is None:
            logger.error(
                "Unknown Circle blockchain %r for wallet_id=%s user=%s notification_id=%s",
                blockchain,
                wallet_id,
                user.id,
                notification_id,
            )
            return

        with transaction.atomic():
            deposit = Deposit.objects.create(
                user=user,
                amount=deposit_amount,
                network=network,
                from_address="",
                circle_notification_id=notification_id,
            )
            deposit.set_paid()

            distribution = Dist("DEPOSIT", deposit_amount, give_rep=False)
            distributor = Distributor(distribution, user, deposit, time.time(), user)
            distributor.distribute()

        logger.info(
            "Circle deposit credited: user=%s amount=%s blockchain=%s network=%s notification_id=%s",
            user.id,
            deposit_amount,
            blockchain,
            network,
            notification_id,
        )
