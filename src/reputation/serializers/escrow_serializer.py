from rest_framework import serializers

from reputation.models import Escrow


class EscrowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Escrow
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicEscrowSerializer:
    pass
