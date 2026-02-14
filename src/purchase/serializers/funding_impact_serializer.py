from rest_framework import serializers


class MilestoneSerializer(serializers.Serializer):
    current = serializers.FloatField()
    target = serializers.FloatField()


class MilestonesSerializer(serializers.Serializer):
    funding_contributed = MilestoneSerializer()
    researchers_supported = MilestoneSerializer()
    matched_funding = MilestoneSerializer()


class FundingTimePointSerializer(serializers.Serializer):
    month = serializers.CharField()
    user_contributions = serializers.FloatField()
    matched_contributions = serializers.FloatField()


class HubFundingSerializer(serializers.Serializer):
    name = serializers.CharField()
    amount_usd = serializers.FloatField()


class UpdateFrequencyBucketSerializer(serializers.Serializer):
    bucket = serializers.CharField()
    count = serializers.IntegerField()


class FundingImpactSerializer(serializers.Serializer):
    """Serializer for funding impact response."""

    milestones = MilestonesSerializer()
    funding_over_time = FundingTimePointSerializer(many=True)
    hub_breakdown = HubFundingSerializer(many=True)
    update_frequency = UpdateFrequencyBucketSerializer(many=True)
