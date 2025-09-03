from rest_framework import serializers


class AddressEntrySerializer(serializers.Serializer):
    """Serializer for wallet address entries."""

    address = serializers.CharField(
        required=True,
        help_text="Wallet address (e.g., 0x123... for Ethereum/Base, bc1... for Bitcoin)",
    )
    blockchains = serializers.ListField(
        child=serializers.CharField(),
        required=True,
        help_text="List of blockchain networks (e.g., ['ethereum', 'base', 'bitcoin'])",
    )


class CoinbaseSerializer(serializers.Serializer):
    """Serializer for Coinbase URL generation requests."""

    addresses = serializers.ListField(
        child=AddressEntrySerializer(),
        required=True,
        min_length=1,
        help_text="List of wallet addresses with their supported blockchains",
    )

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
        min_value=0.00001,
        help_text="Preset crypto amount",
    )

    default_asset = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Default asset to preselect (e.g., 'ETH', 'USDC')",
    )
