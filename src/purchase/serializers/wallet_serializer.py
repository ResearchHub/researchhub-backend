import rest_framework.serializers as serializers

from purchase.models import (
    Wallet,
)

class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = "__all__"
