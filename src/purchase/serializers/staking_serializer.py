from rest_framework import serializers

from purchase.models import FundingCredit, StakingDistributionRecord, StakingSnapshot


class FundingCreditSerializer(serializers.ModelSerializer):
    """Serializer for funding credit transactions."""

    class Meta:
        model = FundingCredit
        fields = [
            "id",
            "amount",
            "credit_type",
            "created_date",
        ]
        read_only_fields = fields


class FundingCreditBalanceSerializer(serializers.Serializer):
    """Serializer for funding credit balance response."""

    balance = serializers.DecimalField(max_digits=19, decimal_places=10)
    recent_transactions = FundingCreditSerializer(many=True)


class StakingInfoSerializer(serializers.Serializer):
    """Serializer for user staking information."""

    rsc_balance = serializers.DecimalField(max_digits=19, decimal_places=10)
    weighted_balance = serializers.DecimalField(max_digits=19, decimal_places=10)
    current_multiplier = serializers.DecimalField(max_digits=5, decimal_places=2)
    multiplier_tier = serializers.CharField()
    days_held = serializers.IntegerField()
    days_until_next_tier = serializers.IntegerField(allow_null=True)
    projected_weekly_credits = serializers.DecimalField(max_digits=19, decimal_places=10)
    projected_apy = serializers.DecimalField(max_digits=5, decimal_places=2)


class StakingSnapshotSerializer(serializers.ModelSerializer):
    """Serializer for staking snapshots."""

    class Meta:
        model = StakingSnapshot
        fields = [
            "id",
            "snapshot_date",
            "rsc_balance",
            "multiplier",
            "weighted_balance",
            "created_date",
        ]
        read_only_fields = fields


class StakingDistributionRecordSerializer(serializers.ModelSerializer):
    """Serializer for staking distribution records."""

    class Meta:
        model = StakingDistributionRecord
        fields = [
            "id",
            "distribution_date",
            "total_pool_amount",
            "total_weighted_balance",
            "users_rewarded",
            "status",
            "created_date",
        ]
        read_only_fields = fields


class StakingHistorySerializer(serializers.Serializer):
    """Serializer for staking history response."""

    snapshots = StakingSnapshotSerializer(many=True)
    distributions = StakingDistributionRecordSerializer(many=True)
