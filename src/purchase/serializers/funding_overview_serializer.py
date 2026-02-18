from rest_framework import serializers


class ActiveGrantsSerializer(serializers.Serializer):
    active = serializers.IntegerField()
    total = serializers.IntegerField()


class ApplicantsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    active = serializers.IntegerField()
    previous = serializers.IntegerField()


class FundingOverviewSerializer(serializers.Serializer):
    """Serializer for funding overview response."""

    total_distributed_usd = serializers.FloatField()
    active_grants = ActiveGrantsSerializer()
    total_applicants = ApplicantsSerializer()
    matched_funding_usd = serializers.FloatField()
    proposals_funded = serializers.IntegerField()
