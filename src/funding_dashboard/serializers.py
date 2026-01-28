from rest_framework import serializers


class ActiveRfpsSerializer(serializers.Serializer):
    active = serializers.IntegerField()
    total = serializers.IntegerField()


class DashboardOverviewSerializer(serializers.Serializer):
    total_distributed_usd = serializers.FloatField()
    active_rfps = ActiveRfpsSerializer()
    total_applicants = serializers.IntegerField()
    matched_funding_usd = serializers.FloatField()
    recent_updates = serializers.IntegerField()
    proposals_funded = serializers.IntegerField()

