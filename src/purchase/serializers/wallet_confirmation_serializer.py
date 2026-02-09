from rest_framework import serializers

from purchase.related_models.wallet_confirmation_model import WalletConfirmation


class WalletConfirmationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletConfirmation
        fields = ["id", "address", "status", "confirmed_at", "created_date"]
        read_only_fields = ["id", "status", "confirmed_at", "created_date"]
