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


class AddReferralCodeSerializer(serializers.Serializer):
    """Serializer for adding referral codes to users."""

    user_id = serializers.IntegerField(required=True)
    referral_code = serializers.CharField(required=True, max_length=36)

    def validate_user_id(self, value):
        """Validate the user exists."""
        try:
            User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        return value

    def validate_referral_code(self, value):
        """Validate the referral code exists."""
        try:
            User.objects.get(referral_code=value.strip())
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid referral code.")
        return value.strip()

    def validate(self, attrs):
        """Validate the referral relationship can be created."""
        user_id = attrs.get("user_id")
        referral_code = attrs.get("referral_code")

        try:
            referred_user = User.objects.get(id=user_id)
            referrer_user = User.objects.get(referral_code=referral_code)

            # Check if user is trying to refer themselves
            if referred_user.id == referrer_user.id:
                raise serializers.ValidationError("Users cannot refer themselves.")

            # Check if referral relationship already exists
            if ReferralSignup.objects.filter(referred=referred_user).exists():
                raise serializers.ValidationError(
                    "This user has already been referred."
                )

        except User.DoesNotExist:
            pass  # Already handled in field validators

        return attrs
