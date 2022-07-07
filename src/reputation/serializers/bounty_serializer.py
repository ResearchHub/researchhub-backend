from rest_framework import serializers

from reputation.models import Bounty


class BountySerializer(serializers.ModelSerializer):
    class Meta:
        model = Bounty
        fields = "__all__"
        read_only_fields = [
            "amount",
            "token_address",
            "from_address",
            "transaction_hash",
            "paid_date",
            "paid_status",
            "is_removed",
            "is_removed_date",
        ]
