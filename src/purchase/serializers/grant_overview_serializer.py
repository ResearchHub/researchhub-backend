from rest_framework import serializers


class GrantOverviewSerializer(serializers.Serializer):
    """Serializer for grant-specific overview response."""

    budget_used_usd = serializers.FloatField()
    budget_total_usd = serializers.FloatField()
    matched_funding_usd = serializers.FloatField()
    recent_updates = serializers.IntegerField()
    proposals_with_updates = serializers.IntegerField()
    total_proposals = serializers.IntegerField()
    proposals_funded = serializers.IntegerField()
    deadline = serializers.CharField(allow_null=True)
