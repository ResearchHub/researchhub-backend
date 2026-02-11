import secrets
from datetime import timedelta

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from web3 import Web3

from ethereum.lib import verify_wallet_signature
from purchase.related_models.wallet_model import Wallet
from purchase.serializers.wallet_serializer import WalletSerializer

NONCE_EXPIRY_MINUTES = 10

VERIFICATION_MESSAGE_TEMPLATE = (
    "ResearchHub Wallet Verification\n"
    "\n"
    "I am verifying ownership of this wallet for my ResearchHub account.\n"
    "\n"
    "Wallet: {address}\n"
    "Nonce: {nonce}"
)


class WalletViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = WalletSerializer

    def get_queryset(self):
        return Wallet.objects.filter(user=self.request.user, status=Wallet.CONFIRMED)

    def list(self, request):
        """List all confirmed wallets for the authenticated user."""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="request_verification")
    def request_verification(self, request):
        """Generate a challenge message for wallet ownership verification."""
        address = request.data.get("address")
        if not address:
            return Response(
                {"error": "address is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            checksum_address = Web3.to_checksum_address(address)
        except ValueError:
            return Response(
                {"error": "Invalid Ethereum address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Delete any existing PENDING verifications for this user + address
        Wallet.objects.filter(
            user=request.user,
            address=checksum_address,
            status=Wallet.PENDING,
        ).delete()

        nonce = secrets.token_hex(32)
        confirmation = Wallet.objects.create(
            user=request.user,
            address=checksum_address,
            nonce=nonce,
            status=Wallet.PENDING,
        )

        message = VERIFICATION_MESSAGE_TEMPLATE.format(
            address=checksum_address, nonce=nonce
        )

        return Response(
            {
                "id": confirmation.id,
                "message": message,
                "nonce": nonce,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"])
    def confirm(self, request):
        """Confirm wallet ownership by verifying a signed challenge message."""
        address = request.data.get("address")
        signature = request.data.get("signature")
        network = request.data.get("network", "ETHEREUM")

        if not address or not signature:
            return Response(
                {"error": "address and signature are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            checksum_address = Web3.to_checksum_address(address)
        except ValueError:
            return Response(
                {"error": "Invalid Ethereum address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if network not in ("ETHEREUM", "BASE"):
            return Response(
                {"error": "network must be ETHEREUM or BASE."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Look up the pending confirmation
        try:
            confirmation = Wallet.objects.get(
                user=request.user,
                address=checksum_address,
                status=Wallet.PENDING,
            )
        except Wallet.DoesNotExist:
            return Response(
                {"error": "No pending verification found for this address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check nonce expiry
        expiry_time = confirmation.created_date + timedelta(
            minutes=NONCE_EXPIRY_MINUTES
        )
        if timezone.now() > expiry_time:
            confirmation.delete()
            return Response(
                {"error": "Verification nonce has expired. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reconstruct the message
        message = VERIFICATION_MESSAGE_TEMPLATE.format(
            address=checksum_address, nonce=confirmation.nonce
        )

        # Verify signature
        try:
            is_valid = verify_wallet_signature(
                checksum_address, message, signature, network=network
            )
        except ValueError:
            return Response(
                {"error": "Signature verification failed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not is_valid:
            return Response(
                {"error": "Invalid signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if this address is already confirmed by another user
        existing = Wallet.objects.filter(
            address=checksum_address, status=Wallet.CONFIRMED
        ).exclude(user=request.user)
        if existing.exists():
            return Response(
                {"error": "This address is already confirmed by another user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If the same user already has a confirmed entry for this address,
        # delete the pending one (idempotent)
        existing_own = Wallet.objects.filter(
            user=request.user,
            address=checksum_address,
            status=Wallet.CONFIRMED,
        ).first()
        if existing_own:
            confirmation.delete()
            serializer = self.get_serializer(existing_own)
            return Response(serializer.data, status=status.HTTP_200_OK)

        confirmation.status = Wallet.CONFIRMED
        confirmation.confirmed_at = timezone.now()
        confirmation.save()

        serializer = self.get_serializer(confirmation)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, pk=None):
        """Remove a confirmed wallet."""
        try:
            confirmation = Wallet.objects.get(
                pk=pk, user=request.user, status=Wallet.CONFIRMED
            )
        except Wallet.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        confirmation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
