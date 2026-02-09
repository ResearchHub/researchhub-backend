from rest_framework import serializers


class ActiveGrantsSerializer(serializers.Serializer):
    active = serializers.IntegerField()
    total = serializers.IntegerField()


class FundingOverviewSerializer(serializers.Serializer):
    """Serializer for funding overview response."""

    total_distributed_usd = serializers.FloatField()
    active_grants = ActiveGrantsSerializer()
    total_applicants = serializers.IntegerField()
    matched_funding_usd = serializers.FloatField()
    recent_updates = serializers.IntegerField()
    proposals_funded = serializers.IntegerField()
