from rest_framework import serializers

from referral.models import ReferralSignup
from user.models import User


class NetworkFundingPowerSerializer(serializers.Serializer):
    """Serializer for network funding power metrics."""

    total_deployed = serializers.FloatField()
    total_potential_impact = serializers.FloatField()
    breakdown = serializers.DictField()


class ReferralActivitySerializer(serializers.Serializer):
    """Serializer for referral activity metrics."""

    funders_invited = serializers.IntegerField()
    active_funders = serializers.IntegerField()


class FundingCreditsSerializer(serializers.Serializer):
    """Serializer for user's funding credits."""

    available = serializers.FloatField()
    total_earned = serializers.FloatField()
    used = serializers.FloatField()


class NetworkEarnedCreditsSerializer(serializers.Serializer):
    """Serializer for network earned credits."""

    total = serializers.FloatField()
    by_referred_users = serializers.FloatField()


class ReferralMetricsSerializer(serializers.Serializer):
    """Main serializer for comprehensive referral metrics."""

    network_funding_power = NetworkFundingPowerSerializer()
    referral_activity = ReferralActivitySerializer()
    your_funding_credits = FundingCreditsSerializer()
    network_earned_credits = NetworkEarnedCreditsSerializer()


class ReferralNetworkDetailSerializer(serializers.Serializer):
    """Serializer for individual referred user details."""

    user_id = serializers.IntegerField()
    username = serializers.CharField()
    signup_date = serializers.DateTimeField()
    total_funded = serializers.FloatField()
    referral_bonus_earned = serializers.FloatField()
    is_active_funder = serializers.BooleanField()


class ReferralSignupSerializer(serializers.ModelSerializer):
    """Serializer for ReferralSignup model."""

    referrer_username = serializers.CharField(
        source="referrer.username", read_only=True
    )
    referred_username = serializers.CharField(
        source="referred.username", read_only=True
    )

    class Meta:
        model = ReferralSignup
        fields = [
            "id",
            "referrer",
            "referrer_username",
            "referred",
            "referred_username",
            "signup_date",
        ]
        read_only_fields = ["id", "signup_date"]
