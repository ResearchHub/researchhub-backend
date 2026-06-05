from decimal import Decimal

from rest_framework import serializers


class CoinbaseSerializer(serializers.Serializer):
    """Serializer for Coinbase URL generation requests."""

    assets = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Optional list of asset tickers to restrict (e.g., ['ETH', 'USDC'])",
    )

    default_network = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Default network to preselect (e.g., 'base', 'ethereum')",
    )

    preset_fiat_amount = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Preset fiat amount in the currency",
    )

    preset_crypto_amount = serializers.FloatField(
        required=False,
        min_value=Decimal("0.00001"),
        help_text="Preset crypto amount",
    )

    default_asset = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Default asset to preselect (e.g., 'ETH', 'USDC')",
    )


class CoinbaseSessionTokenSerializer(serializers.Serializer):
    """Serializer for Coinbase session token requests."""

    assets = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Optional list of asset tickers to restrict (e.g., ['ETH', 'USDC'])",
    )
