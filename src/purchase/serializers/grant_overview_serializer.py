from rest_framework import serializers

from purchase.serializers.funding_overview_serializer import ImpactDataSerializer


class GrantOverviewSerializer(serializers.Serializer):
    """Serializer for grant-specific overview response."""

    total_raised_usd = serializers.FloatField()
    total_applicants = serializers.IntegerField()
    matched_funding_usd = serializers.FloatField()
    recent_updates = serializers.IntegerField()
    impact = ImpactDataSerializer()
