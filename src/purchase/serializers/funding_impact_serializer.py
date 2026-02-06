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


class TopicFundingSerializer(serializers.Serializer):
    name = serializers.CharField()
    amount_usd = serializers.FloatField()


class UpdateFrequencyBucketSerializer(serializers.Serializer):
    bucket = serializers.CharField()
    count = serializers.IntegerField()


class InstitutionFundingSerializer(serializers.Serializer):
    name = serializers.CharField()
    ein = serializers.CharField(allow_blank=True)
    location = serializers.CharField(allow_blank=True, required=False)
    amount_usd = serializers.FloatField()
    project_count = serializers.IntegerField()


class FundingImpactSerializer(serializers.Serializer):
    """Serializer for funding impact response."""

    milestones = MilestonesSerializer()
    funding_over_time = FundingTimePointSerializer(many=True)
    topic_breakdown = TopicFundingSerializer(many=True)
    update_frequency = UpdateFrequencyBucketSerializer(many=True)
    institutions_supported = InstitutionFundingSerializer(many=True)
