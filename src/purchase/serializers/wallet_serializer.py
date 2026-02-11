from rest_framework import serializers

from purchase.related_models.wallet_model import Wallet


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = [
            "id",
            "address",
            "status",
            "wallet_type",
            "confirmed_at",
            "created_date",
        ]
        read_only_fields = [
            "id",
            "status",
            "wallet_type",
            "confirmed_at",
            "created_date",
        ]
