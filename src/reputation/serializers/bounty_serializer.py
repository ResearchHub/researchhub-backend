from rest_framework import serializers

from reputation.models import Bounty


class BountySerializer(serializers.ModelSerializer):
    class Meta:
        model = Bounty
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
        ]


class DynamicBountySerializer:
    pass
