import rest_framework.serializers as serializers

from purchase.models import (
    RscExchangeRate,
)


class RscExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RscExchangeRate
        fields = "__all__"
