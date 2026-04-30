from rest_framework import serializers


class StakingYieldDetailsSerializer(serializers.Serializer):
    is_staking_opted_in = serializers.BooleanField()
    staking_opted_in_date = serializers.DateTimeField(allow_null=True)
    current_stake = serializers.DecimalField(max_digits=19, decimal_places=8)
    current_multiplier = serializers.DecimalField(max_digits=19, decimal_places=8)
    current_weighted_stake = serializers.DecimalField(max_digits=19, decimal_places=8)
    total_yield_earned = serializers.DecimalField(max_digits=19, decimal_places=8)
    latest_accrual_date = serializers.DateField(allow_null=True)
    apy = serializers.FloatField()


class StakingYieldEarnedSinceSerializer(serializers.Serializer):
    since_date = serializers.DateField()
    yield_earned = serializers.DecimalField(max_digits=19, decimal_places=8)


class StakingStatsSerializer(serializers.Serializer):
    accrual_date = serializers.DateField(allow_null=True)
    apy = serializers.FloatField()
    apy_30d_avg = serializers.FloatField()
    holders = serializers.IntegerField()
    top_10_concentration_pct = serializers.FloatField()
    total_staked_rsc = serializers.DecimalField(max_digits=19, decimal_places=8)
    total_value_locked_usd = serializers.DecimalField(
        max_digits=19, decimal_places=2, allow_null=True
    )
    circulating_supply_rsc = serializers.DecimalField(max_digits=19, decimal_places=8)
    pct_of_supply_staked = serializers.FloatField()


class StakingHistoryEntrySerializer(serializers.Serializer):
    accrual_date = serializers.DateField()
    apy = serializers.FloatField()
    total_staked_rsc = serializers.DecimalField(max_digits=19, decimal_places=8)
    total_value_locked_usd = serializers.DecimalField(
        max_digits=19, decimal_places=2, allow_null=True
    )
    holders = serializers.IntegerField()
