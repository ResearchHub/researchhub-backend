import rest_framework.serializers as serializers

from purchase.models import (
    Support,
)


class SupportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Support
        fields = "__all__"
