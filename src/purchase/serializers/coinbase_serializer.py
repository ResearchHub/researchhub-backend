from rest_framework import serializers


class AddressSerializer(serializers.Serializer):
    """Serializer for wallet address with supported blockchains."""

    address = serializers.CharField(required=True, help_text="Wallet address")
    blockchains = serializers.ListField(
        child=serializers.CharField(),
        required=True,
        help_text="List of supported blockchains (e.g., ['ethereum', 'base'])",
    )


class CoinbaseSessionSerializer(serializers.Serializer):
    """Serializer for Coinbase session token creation."""

    addresses = serializers.ListField(
        child=AddressSerializer(),
        required=True,
        help_text="List of wallet addresses with their supported blockchains",
    )
    assets = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Optional list of supported assets (e.g., ['ETH', 'USDC'])",
    )
