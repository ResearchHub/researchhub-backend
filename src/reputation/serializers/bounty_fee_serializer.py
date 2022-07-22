from rest_framework import serializers

from reputation.models import BountyFee
from researchhub.serializers import DynamicModelFieldSerializer


class BountyFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BountyFee
        fields = "__all__"


class DynamicBountyFeeSerializer(DynamicModelFieldSerializer):
    class Meta:
        model = BountyFee
        fields = "__all__"
