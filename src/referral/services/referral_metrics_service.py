from decimal import Decimal

from django.db.models import DecimalField, Sum
from django.db.models.functions import Cast

from purchase.models import Purchase
from purchase.related_models.balance_model import Balance
from referral.models import ReferralSignup
from reputation.related_models.distribution import Distribution


class ReferralMetricsService:
    """Service for calculating referral network metrics and funding impact."""

    def __init__(self, user):
        self.user = user
        self.bonus_percentage = Decimal("10.00")

    def get_comprehensive_metrics(self):
        """
        Get comprehensive referral metrics for a user including:
        - Network funding power
        - Referral activity
        - Funding credits
        - Network earned credits
        """
        metrics = {
            "network_funding_power": self._calculate_network_funding_power(),
            "referral_activity": self._calculate_referral_activity(),
            "your_funding_credits": self._calculate_user_funding_credits(),
            "network_earned_credits": self._calculate_network_earned_credits(),
        }
        return metrics

    def _calculate_network_funding_power(self):
        """
        Calculate the total funding power of the user's referral network.

        Returns:
            dict: Contains total_deployed, total_potential_impact, and breakdown
        """
        # Direct funding by the user (fundraise contributions)
        direct_funding = self._get_user_direct_funding()

        # Funding by referred users
        network_funding = self._get_network_funding()

        # Credits used from referral bonuses
        credits_used = self._get_used_referral_credits()

        # Total deployed = direct + network + used credits
        total_deployed = direct_funding + network_funding + credits_used

        # Available credits that could still be deployed
        available_credits = self._get_available_referral_credits()
        network_available_credits = self._get_network_available_credits()

        # Total potential = deployed + available credits
        total_potential_impact = (
            total_deployed + available_credits + network_available_credits
        )

        return {
            "total_deployed": float(total_deployed),
            "total_potential_impact": float(total_potential_impact),
            "breakdown": {
                "direct_funding": float(direct_funding),
                "network_funding": float(network_funding),
                "credits_used": float(credits_used),
                "available_credits": float(available_credits),
                "network_available_credits": float(network_available_credits),
            },
        }

    def _calculate_referral_activity(self):
        """
        Calculate referral activity metrics.

        Returns:
            dict: Contains funders_invited and active_funders count
        """
        # Get all users referred by this user
        referred_users = ReferralSignup.objects.filter(
            referrer=self.user
        ).select_related("referred")

        total_invited = referred_users.count()

        # Active funders are those who have made at least one contribution
        active_funders = (
            referred_users.filter(
                referred__purchases__purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                referred__purchases__paid_status=Purchase.PAID,
            )
            .distinct()
            .count()
        )

        return {
            "funders_invited": total_invited,
            "active_funders": active_funders,
        }

    def _calculate_user_funding_credits(self):
        """
        Calculate the user's own funding credits from referral bonuses.

        Returns:
            dict: Contains available, total_earned, and used amounts
        """
        # Get all referral bonus distributions for this user
        referral_distributions = Distribution.objects.filter(
            recipient=self.user,
            distribution_type="REFERRAL_BONUS",
            distributed_status=Distribution.DISTRIBUTED,
        )

        total_earned = referral_distributions.aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )["total"] or Decimal("0")

        # Get available balance (locked referral bonus balance)
        available = Balance.objects.filter(
            user=self.user, is_locked=True, lock_type="REFERRAL_BONUS"
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

        # Used = total earned - available
        used = total_earned - available

        return {
            "available": float(available),
            "total_earned": float(total_earned),
            "used": float(used),
        }

    def _calculate_network_earned_credits(self):
        """
        Calculate total credits earned by users referred by this user.

        Returns:
            dict: Contains total credits earned by referred users
        """
        # Get all users referred by this user
        referred_user_ids = ReferralSignup.objects.filter(
            referrer=self.user
        ).values_list("referred_id", flat=True)

        # Get total referral bonuses earned by these users
        network_earned = Distribution.objects.filter(
            recipient_id__in=referred_user_ids,
            distribution_type="REFERRAL_BONUS",
            distributed_status=Distribution.DISTRIBUTED,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

        return {
            "total": float(network_earned),
            "by_referred_users": float(network_earned),
        }

    def _get_user_direct_funding(self):
        """Get total direct funding contributions by the user."""
        return Purchase.objects.filter(
            user=self.user,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

    def _get_network_funding(self):
        """Get total funding by users referred by this user."""
        referred_user_ids = ReferralSignup.objects.filter(
            referrer=self.user
        ).values_list("referred_id", flat=True)

        return Purchase.objects.filter(
            user_id__in=referred_user_ids,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

    def _get_used_referral_credits(self):
        """
        Get the amount of referral credits that have been used (unlocked and spent).
        This represents referral bonus funds that were used for funding.
        """
        # First, get total earned referral bonuses
        total_earned = Distribution.objects.filter(
            recipient=self.user,
            distribution_type="REFERRAL_BONUS",
            distributed_status=Distribution.DISTRIBUTED,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

        # Then get current locked balance
        locked_balance = Balance.objects.filter(
            user=self.user, is_locked=True, lock_type="REFERRAL_BONUS"
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

        # Used = earned - still locked
        # Assuming unlocked funds were used for funding
        return total_earned - locked_balance

    def _get_available_referral_credits(self):
        """Get available (locked) referral bonus credits for the user."""
        return Balance.objects.filter(
            user=self.user, is_locked=True, lock_type="REFERRAL_BONUS"
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

    def _get_network_available_credits(self):
        """Get total available credits for all referred users."""
        referred_user_ids = ReferralSignup.objects.filter(
            referrer=self.user
        ).values_list("referred_id", flat=True)

        return Balance.objects.filter(
            user_id__in=referred_user_ids, is_locked=True, lock_type="REFERRAL_BONUS"
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )

    def get_referral_network_details(self):
        """
        Get detailed information about each referred user and their activity.

        Returns:
            list: List of referred users with their funding activity
        """
        referred_signups = (
            ReferralSignup.objects.filter(referrer=self.user)
            .select_related("referred", "referred__author_profile")
            .order_by("-signup_date")
        )

        network_details = []
        for signup in referred_signups:
            user_data = {
                "user_id": signup.referred.id,
                "username": signup.referred.username,
                "full_name": signup.referred.full_name(),
                "profile_image": self._get_user_profile_image(signup.referred),
                "signup_date": signup.signup_date,
                "total_funded": self._get_user_total_funded(signup.referred),
                "referral_bonus_earned": self._get_user_referral_bonus(signup.referred),
                "is_active_funder": self._is_active_funder(signup.referred),
            }
            network_details.append(user_data)

        return network_details

    def _get_user_total_funded(self, user):
        """Get total amount funded by a specific user."""
        total = Purchase.objects.filter(
            user=user,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )
        return float(total)

    def _get_user_referral_bonus(self, user):
        """Get total referral bonus earned by a specific user."""
        total = Distribution.objects.filter(
            recipient=user,
            distribution_type="REFERRAL_BONUS",
            distributed_status=Distribution.DISTRIBUTED,
        ).aggregate(
            total=Sum(Cast("amount", DecimalField(max_digits=19, decimal_places=8)))
        )[
            "total"
        ] or Decimal(
            "0"
        )
        return float(total)

    def _is_active_funder(self, user):
        """Check if a user has made any funding contributions."""
        return Purchase.objects.filter(
            user=user,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
        ).exists()

    def _get_user_profile_image(self, user):
        """Get the profile image URL for a user."""
        if (
            hasattr(user, "author_profile")
            and user.author_profile
            and user.author_profile.profile_image
        ):
            return user.author_profile.profile_image.url
        return None
