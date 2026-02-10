from rest_framework import serializers


class GrantOverviewSerializer(serializers.Serializer):
    """Serializer for grant-specific overview response."""

    total_raised_usd = serializers.FloatField()
    total_applicants = serializers.IntegerField()
    matched_funding_usd = serializers.FloatField()
    recent_updates = serializers.IntegerField()
