from rest_framework import serializers


class CurrencyBreakdownSerializer(serializers.Serializer):
    rsc = serializers.FloatField()
    rsc_usd_snapshot = serializers.FloatField()
    usd = serializers.FloatField()


class EarningOverviewSerializer(serializers.Serializer):
    """Serializer for GET /api/user/earning_overview/."""

    total_earned = CurrencyBreakdownSerializer()
    by_source = serializers.DictField(child=CurrencyBreakdownSerializer())
