from rest_framework import serializers


class ActiveGrantsSerializer(serializers.Serializer):
    active = serializers.IntegerField()
    total = serializers.IntegerField()


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
    amount_usd = serializers.FloatField()
    project_count = serializers.IntegerField()


class ImpactDataSerializer(serializers.Serializer):
    milestones = MilestonesSerializer()
    funding_over_time = FundingTimePointSerializer(many=True)
    topic_breakdown = TopicFundingSerializer(many=True)
    update_frequency = UpdateFrequencyBucketSerializer(many=True)
    institutions_supported = InstitutionFundingSerializer(many=True)


class FundingOverviewSerializer(serializers.Serializer):
    """Serializer for funding overview response."""

    total_distributed_usd = serializers.FloatField()
    active_grants = ActiveGrantsSerializer()
    total_applicants = serializers.IntegerField()
    matched_funding_usd = serializers.FloatField()
    recent_updates = serializers.IntegerField()
    proposals_funded = serializers.IntegerField()
    impact = ImpactDataSerializer()
