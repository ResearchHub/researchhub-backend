from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from purchase.models import Purchase
from referral.models import ReferralSignup
from reputation.distributions import create_referral_bonus_distribution
from reputation.distributor import Distributor


class ReferralBonusService:
    """Service for processing referral bonuses when fundraises complete."""

    REFERRAL_ELIGIBILITY_MONTHS = 6
    BONUS_PERCENTAGE = 10.00

    @classmethod
    def process_fundraise_completion(cls, fundraise):
        """
        Process referral bonuses for a completed fundraise.

        Args:
            fundraise: The completed Fundraise instance
        """
        with transaction.atomic():
            eligible_referrals = cls._get_eligible_referrals(fundraise)

            for referral_data in eligible_referrals:
                cls._distribute_referral_bonus(
                    fundraise=fundraise,
                    referred_user=referral_data["referred_user"],
                    referrer_user=referral_data["referrer_user"],
                    contribution_amount=referral_data["contribution_amount"],
                )

    @classmethod
    def _get_eligible_referrals(cls, fundraise):
        """
        Get all referrals eligible for bonuses for this fundraise.

        Returns:
            List of dicts with referral data
        """
        cutoff_date = timezone.now() - timedelta(
            days=30 * cls.REFERRAL_ELIGIBILITY_MONTHS
        )

        # Get all contributions to this fundraise
        contributions = Purchase.objects.filter(
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            content_type__model="fundraise",
            object_id=fundraise.id,
            paid_status=Purchase.PAID,
        ).select_related("user")

        eligible_referrals = []

        for contribution in contributions:
            try:
                # Check if this user was referred within eligibility period
                referral_signup = ReferralSignup.objects.select_related(
                    "referrer", "referred"
                ).get(referred=contribution.user, signup_date__gte=cutoff_date)

                eligible_referrals.append(
                    {
                        "referred_user": contribution.user,
                        "referrer_user": referral_signup.referrer,
                        "contribution_amount": contribution.amount,
                        "referral_signup": referral_signup,
                    }
                )

            except ReferralSignup.DoesNotExist:
                continue

        return eligible_referrals

    @classmethod
    def _distribute_referral_bonus(
        cls,
        fundraise,
        referred_user,
        referrer_user,
        contribution_amount,
    ):
        """
        Distribute referral bonus to both the referred user and referrer.

        Args:
            fundraise: The completed fundraise
            referred_user: User who was referred and contributed
            referrer_user: User who made the referral
            contribution_amount: Amount the referred user contributed
        """
        # Convert percentage to decimal (e.g., 10.00 -> 0.10)
        bonus_percentage_decimal = cls.BONUS_PERCENTAGE / 100
        bonus_amount = contribution_amount * bonus_percentage_decimal
        timestamp = timezone.now().timestamp()

        # Create bonus distribution for the referred user (contributor)
        referred_distribution = create_referral_bonus_distribution(bonus_amount)
        referred_distributor = Distributor(
            distribution=referred_distribution,
            recipient=referred_user,
            proof_item=fundraise,
            timestamp=timestamp,
            giver=None,  # Platform gives the bonus
        )
        referred_distributor.distribute_locked_balance(lock_type="REFERRAL_BONUS")

        # Create bonus distribution for the referrer
        referrer_distribution = create_referral_bonus_distribution(bonus_amount)
        referrer_distributor = Distributor(
            distribution=referrer_distribution,
            recipient=referrer_user,
            proof_item=fundraise,
            timestamp=timestamp,
            giver=None,  # Platform gives the bonus
        )
        referrer_distributor.distribute_locked_balance(lock_type="REFERRAL_BONUS")
