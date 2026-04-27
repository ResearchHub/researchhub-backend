from rest_framework import serializers


class StakingBalanceLotSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=19, decimal_places=8)
    created_date = serializers.DateField()
    effective_start_date = serializers.DateField()
    age_days = serializers.IntegerField()
    current_multiplier = serializers.DecimalField(max_digits=19, decimal_places=8)
    next_multiplier = serializers.DecimalField(
        max_digits=19, decimal_places=8, allow_null=True
    )
    days_until_next_multiplier = serializers.IntegerField(allow_null=True)
    next_multiplier_date = serializers.DateField(allow_null=True)
    projected_overall_multiplier = serializers.DecimalField(
        max_digits=19, decimal_places=8, allow_null=True
    )


class StakingYieldDetailsSerializer(serializers.Serializer):
    is_staking_opted_in = serializers.BooleanField()
    staking_opted_in_date = serializers.DateTimeField(allow_null=True)
    current_stake = serializers.DecimalField(max_digits=19, decimal_places=8)
    current_multiplier = serializers.DecimalField(max_digits=19, decimal_places=8)
    current_weighted_stake = serializers.DecimalField(max_digits=19, decimal_places=8)
    total_yield_earned = serializers.DecimalField(max_digits=19, decimal_places=8)
    latest_accrual_date = serializers.DateField(allow_null=True)
    apy = serializers.FloatField()
    balance_lots = StakingBalanceLotSerializer(many=True)


class StakingYieldEarnedSinceSerializer(serializers.Serializer):
    since_date = serializers.DateField()
    yield_earned = serializers.DecimalField(max_digits=19, decimal_places=8)
