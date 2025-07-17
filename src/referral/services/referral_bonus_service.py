from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from purchase.models import Purchase
from referral.constants import REFERRAL_BONUS_PERCENTAGE, REFERRAL_ELIGIBILITY_MONTHS
from referral.models import ReferralSignup
from reputation.distributions import create_referral_bonus_distribution
from reputation.distributor import Distributor


class ReferralBonusService:
    """Service for processing referral bonuses when fundraises complete."""

    def __init__(self):
        self.bonus_percentage = REFERRAL_BONUS_PERCENTAGE
        self.referral_eligibility_months = REFERRAL_ELIGIBILITY_MONTHS

    def process_fundraise_completion(self, fundraise):
        """
        Process referral bonuses for a completed fundraise.

        Args:
            fundraise: The completed Fundraise instance
        """
        with transaction.atomic():
            eligible_referrals = self._get_eligible_referrals(fundraise)

            for referral_data in eligible_referrals:
                self._distribute_referral_bonus(
                    fundraise=fundraise,
                    referred_user=referral_data["referred_user"],
                    referrer_user=referral_data["referrer_user"],
                    contribution_amount=referral_data["contribution_amount"],
                )

    def _get_eligible_referrals(self, fundraise):
        """
        Get all referrals eligible for bonuses for this fundraise.

        Returns:
            List of dicts with referral data
        """
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
                ).get(referred=contribution.user)

                cutoff_date = referral_signup.signup_date + timedelta(
                    days=30 * self.referral_eligibility_months
                )
                if contribution.created_date > cutoff_date:
                    continue

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

    def _distribute_referral_bonus(
        self,
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
        bonus_percentage_decimal = self.bonus_percentage / 100
        bonus_amount = Decimal(contribution_amount) * bonus_percentage_decimal
        timestamp = timezone.now().timestamp()

        # Create bonus distribution for the referred user (contributor)
        referred_distribution = create_referral_bonus_distribution(bonus_amount)
        referred_distributor = Distributor(
            distribution=referred_distribution,
            recipient=referred_user,
            db_record=fundraise,
            timestamp=timestamp,
            giver=None,  # Platform gives the bonus
        )
        referred_distributor.distribute_locked_balance(lock_type="REFERRAL_BONUS")

        # Create bonus distribution for the referrer
        referrer_distribution = create_referral_bonus_distribution(bonus_amount)
        referrer_distributor = Distributor(
            distribution=referrer_distribution,
            recipient=referrer_user,
            db_record=fundraise,
            timestamp=timestamp,
            giver=None,  # Platform gives the bonus
        )
        referrer_distributor.distribute_locked_balance(lock_type="REFERRAL_BONUS")
