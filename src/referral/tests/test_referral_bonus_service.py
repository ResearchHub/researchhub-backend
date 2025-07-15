from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from purchase.models import Balance, Fundraise, Purchase
from referral.models import ReferralSignup
from referral.services.referral_bonus_service import ReferralBonusService
from referral.services.referral_metrics_service import ReferralMetricsService
from reputation.models import Distribution
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_default_user


class ReferralBonusServiceTest(TestCase):
    def setUp(self):
        self.referrer = create_random_default_user("referrer")
        self.referred_user = create_random_default_user("referred")
        self.fundraise_creator = create_random_default_user("creator")

        # Create a post to get a unified document for the fundraise
        self.post = create_post(
            created_by=self.fundraise_creator, document_type=PREREGISTRATION
        )

        # Create a fundraise
        self.fundraise = Fundraise.objects.create(
            created_by=self.fundraise_creator,
            unified_document=self.post.unified_document,
            goal_amount=Decimal("1000.00"),
            status=Fundraise.COMPLETED,
        )

        # Create referral signup within 6 months
        self.referral_signup = ReferralSignup.objects.create(
            referrer=self.referrer,
            referred=self.referred_user,
            signup_date=timezone.now() - timedelta(days=30),  # 1 month ago
        )

        # Create contribution from referred user
        self.contribution_amount = Decimal("100.00")
        self.purchase = Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=self.contribution_amount,
        )

        # Initialize the service with default parameters
        self.service = ReferralBonusService()

    def test_process_fundraise_completion_creates_bonuses(self):
        """Test that referral bonuses are created for eligible referrals"""
        initial_distribution_count = Distribution.objects.count()
        initial_balance_count = Balance.objects.count()

        self.service.process_fundraise_completion(self.fundraise)

        # Should create 2 distributions (one for referrer, one for referred user)
        self.assertEqual(Distribution.objects.count(), initial_distribution_count + 2)

        # Should create 2 balance entries (locked funds)
        self.assertEqual(Balance.objects.count(), initial_balance_count + 2)

        # Check distributions were created with correct amounts
        expected_bonus = self.contribution_amount * (
            self.service.bonus_percentage / 100
        )
        referrer_distribution = Distribution.objects.filter(
            recipient=self.referrer,
            distribution_type="REFERRAL_BONUS",
            amount=expected_bonus,
        ).first()
        self.assertIsNotNone(referrer_distribution)

        referred_distribution = Distribution.objects.filter(
            recipient=self.referred_user,
            distribution_type="REFERRAL_BONUS",
            amount=expected_bonus,
        ).first()
        self.assertIsNotNone(referred_distribution)

        # Check locked balances were created
        referrer_balance = Balance.objects.filter(
            user=self.referrer, is_locked=True, lock_type="REFERRAL_BONUS"
        ).first()
        self.assertIsNotNone(referrer_balance)

        referred_balance = Balance.objects.filter(
            user=self.referred_user, is_locked=True, lock_type="REFERRAL_BONUS"
        ).first()
        self.assertIsNotNone(referred_balance)

        # Bonuses can be applied multiple times for different fundraises

    def test_old_referrals_not_eligible(self):
        """Test that referrals older than 6 months are not eligible"""
        # Update referral signup to be older than 6 months
        self.referral_signup.signup_date = timezone.now() - timedelta(days=200)
        self.referral_signup.save()

        initial_distribution_count = Distribution.objects.count()

        self.service.process_fundraise_completion(self.fundraise)

        # No distributions should be created
        self.assertEqual(Distribution.objects.count(), initial_distribution_count)

        # No bonuses should be distributed for old referrals

    def test_multiple_fundraise_bonuses(self):
        """Test that bonuses are applied for multiple fundraises"""
        # Process first fundraise
        self.service.process_fundraise_completion(self.fundraise)

        # Create a second fundraise with its own unified document
        second_post = create_post(
            created_by=self.fundraise_creator, document_type=PREREGISTRATION
        )
        second_fundraise = Fundraise.objects.create(
            created_by=self.fundraise_creator,
            unified_document=second_post.unified_document,
            goal_amount=Decimal("500.00"),
            status=Fundraise.COMPLETED,
        )

        # Create contribution to second fundraise
        second_contribution_amount = Decimal("75.00")
        Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=second_fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=second_contribution_amount,
        )

        initial_distribution_count = Distribution.objects.count()

        # Process second fundraise - should create additional bonuses
        self.service.process_fundraise_completion(second_fundraise)

        # Should create 2 more distributions (one for referrer, one for referred user)
        self.assertEqual(Distribution.objects.count(), initial_distribution_count + 2)

        # Check that referrer has received bonuses from both fundraises
        referrer_distributions = Distribution.objects.filter(
            recipient=self.referrer, distribution_type="REFERRAL_BONUS"
        )
        self.assertEqual(
            referrer_distributions.count(), 2
        )  # Two separate fundraise bonuses

    def test_non_referred_users_skipped(self):
        """Test that users without referral signups are skipped"""
        # Create a user without referral signup
        non_referred_user = create_random_default_user("non_referred")
        Purchase.objects.create(
            user=non_referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=Decimal("50.00"),
        )

        initial_distribution_count = Distribution.objects.count()

        self.service.process_fundraise_completion(self.fundraise)

        # Should only create 2 distributions for the referred user
        self.assertEqual(Distribution.objects.count(), initial_distribution_count + 2)

    def test_correct_bonus_calculation(self):
        """Test that bonus amounts are calculated correctly"""
        self.service.process_fundraise_completion(self.fundraise)

        expected_bonus = self.contribution_amount * (
            self.service.bonus_percentage / 100
        )

        referrer_distribution = Distribution.objects.filter(
            recipient=self.referrer, distribution_type="REFERRAL_BONUS"
        ).first()

        self.assertEqual(referrer_distribution.amount, expected_bonus)

    def test_multiple_contributions_from_same_user(self):
        """Test that bonuses are calculated based on total contribution amount"""
        # Create another contribution from the same referred user
        additional_amount = Decimal("50.00")
        Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=additional_amount,
        )

        self.service.process_fundraise_completion(self.fundraise)

        # Should have separate bonuses for each contribution
        referrer_distributions = Distribution.objects.filter(
            recipient=self.referrer, distribution_type="REFERRAL_BONUS"
        )
        self.assertEqual(referrer_distributions.count(), 2)  # One for each contribution

        # Note: Current implementation processes each contribution separately
        # This test documents current behavior - may need adjustment based on requirements

    def test_multiple_referrals_same_fundraise(self):
        """Test that multiple referrals for the same fundraise are processed correctly"""
        # Create another referral
        other_referrer = create_random_default_user("other_referrer")
        other_referred = create_random_default_user("other_referred")

        ReferralSignup.objects.create(
            referrer=other_referrer,
            referred=other_referred,
            signup_date=timezone.now() - timedelta(days=30),
        )

        # Create contribution from other referred user
        other_contribution_amount = Decimal("200.00")
        Purchase.objects.create(
            user=other_referred,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=other_contribution_amount,
        )

        self.service.process_fundraise_completion(self.fundraise)

        # Check first referral
        expected_bonus_1 = self.contribution_amount * (
            self.service.bonus_percentage / 100
        )
        referrer_1_distribution = Distribution.objects.filter(
            recipient=self.referrer, distribution_type="REFERRAL_BONUS"
        ).first()
        self.assertEqual(referrer_1_distribution.amount, expected_bonus_1)

        # Check second referral
        expected_bonus_2 = other_contribution_amount * (
            self.service.bonus_percentage / 100
        )
        referrer_2_distribution = Distribution.objects.filter(
            recipient=other_referrer, distribution_type="REFERRAL_BONUS"
        ).first()
        self.assertEqual(referrer_2_distribution.amount, expected_bonus_2)

    def test_distribution_status_set_to_distributed(self):
        """Test that distribution status is set to DISTRIBUTED for locked balances"""
        self.service.process_fundraise_completion(self.fundraise)

        # Check that all referral bonus distributions have status DISTRIBUTED
        distributions = Distribution.objects.filter(distribution_type="REFERRAL_BONUS")

        self.assertEqual(distributions.count(), 2)  # One for referrer, one for referred

        for distribution in distributions:
            self.assertEqual(
                distribution.distributed_status,
                Distribution.DISTRIBUTED,
                f"Distribution {distribution.id} should have status DISTRIBUTED",
            )
            self.assertIsNotNone(
                distribution.distributed_date,
                f"Distribution {distribution.id} should have distributed_date set",
            )

    def test_credits_earned_shows_correct_amount_in_metrics(self):
        """Test that credits earned calculation includes distributions with DISTRIBUTED status"""
        # Process the fundraise to create referral bonuses
        self.service.process_fundraise_completion(self.fundraise)

        # Get metrics for the referred user
        metrics_service = ReferralMetricsService(self.referred_user)
        user_funding_credits = metrics_service._calculate_user_funding_credits()

        # Calculate expected bonus
        expected_bonus = float(
            self.contribution_amount * (self.service.bonus_percentage / 100)
        )

        # Check that credits earned equals the expected bonus
        self.assertEqual(
            user_funding_credits["total_earned"],
            expected_bonus,
            "Credits earned should equal the referral bonus received",
        )

        # Get network details from referrer's perspective
        referrer_metrics_service = ReferralMetricsService(self.referrer)
        network_details = referrer_metrics_service.get_referral_network_details()

        # Find the referred user in network details
        referred_user_details = next(
            (
                detail
                for detail in network_details
                if detail["user_id"] == self.referred_user.id
            ),
            None,
        )

        self.assertIsNotNone(referred_user_details)
        self.assertEqual(
            referred_user_details["referral_bonus_earned"],
            expected_bonus,
            "Network details should show correct credits earned for referred user",
        )

    def test_contribution_before_referral_expired_and_fundraise_completed_after_referral_expired(
        self,
    ):
        """Test that only contributions within referral period are eligible for bonuses"""
        # Set referral signup to be ~6 months ago (just before expiration)
        six_months_ago = timezone.now() - timedelta(
            days=self.service.referral_eligibility_months * 30
        )
        self.referral_signup.signup_date = six_months_ago - timedelta(days=1)
        self.referral_signup.save()

        # Update the original contribution date to be within the referral window
        self.purchase.created_date = six_months_ago + timedelta(
            days=30
        )  # 1 month after signup
        self.purchase.save()

        # Create two additional contributions:
        # 1. One within the referral bonus period (should get bonus)
        eligible_contribution_amount = Decimal("150.12")
        eligible_contribution = Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=eligible_contribution_amount,
        )
        # Set date to 7 days ago - within the eligibility window
        eligible_contribution.created_date = timezone.now() - timedelta(days=7)
        eligible_contribution.save()

        # 2. One after the referral bonus period expires (should NOT get bonus)
        ineligible_contribution_amount = Decimal("200.00")
        ineligible_contribution = Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=ineligible_contribution_amount,
        )
        # Leave at current date - after the eligibility window
        # Note: This contribution happens after referral expires but before fundraise completes

        # Process fundraise completion (happens after referral expiration)
        self.service.process_fundraise_completion(self.fundraise)

        # Verify that only the eligible contribution created a bonus
        distributions = Distribution.objects.filter(
            recipient=self.referrer,
            distribution_type="REFERRAL_BONUS",
        )

        # Should have 2 distributions: 1 for original setup contribution + 1 for eligible contribution
        self.assertEqual(
            distributions.count(),
            2,
            "Should have bonuses for original contribution and eligible contribution only",
        )

        # Verify the bonus amounts
        expected_original_bonus = self.contribution_amount * (
            self.service.bonus_percentage / 100
        )
        expected_eligible_bonus = eligible_contribution_amount * (
            self.service.bonus_percentage / 100
        )

        total_bonus = sum(d.amount for d in distributions)
        expected_total = expected_original_bonus + expected_eligible_bonus

        self.assertEqual(
            total_bonus,
            expected_total,
            f"Total bonus should be {expected_total} (original: {expected_original_bonus} + "
            f"eligible: {expected_eligible_bonus})",
        )

        # Verify no bonus was created for the ineligible contribution
        # Check that referred user also got correct bonuses
        referred_distributions = Distribution.objects.filter(
            recipient=self.referred_user,
            distribution_type="REFERRAL_BONUS",
        )
        self.assertEqual(
            referred_distributions.count(),
            2,
            "Referred user should also have 2 bonuses",
        )

    def test_contribution_on_referral_expiration_boundary(self):
        """Test edge cases around the exact referral expiration date"""
        # Set referral signup to exactly eligibility period ago
        eligibility_days = self.service.referral_eligibility_months * 30
        eligibility_ago = timezone.now() - timedelta(days=eligibility_days)
        self.referral_signup.signup_date = eligibility_ago
        self.referral_signup.save()

        # Delete the original contribution to have clean test
        self.purchase.delete()

        # Create contribution just before expiration (1 second before)
        before_expiry_contribution = Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=Decimal("100.00"),
        )
        before_expiry_contribution.created_date = (
            eligibility_ago + timedelta(days=eligibility_days) - timedelta(seconds=1)
        )
        before_expiry_contribution.save()

        # Create contribution exactly at expiration
        at_expiry_contribution = Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=Decimal("100.00"),
        )
        at_expiry_contribution.created_date = eligibility_ago + timedelta(
            days=eligibility_days
        )
        at_expiry_contribution.save()

        # Create contribution just after expiration (1 second after)
        after_expiry_contribution = Purchase.objects.create(
            user=self.referred_user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=Decimal("100.00"),
        )
        after_expiry_contribution.created_date = (
            eligibility_ago + timedelta(days=eligibility_days) + timedelta(seconds=1)
        )
        after_expiry_contribution.save()

        self.service.process_fundraise_completion(self.fundraise)

        # Check distributions - should have bonuses for contributions before and at expiry
        distributions = Distribution.objects.filter(
            recipient=self.referrer,
            distribution_type="REFERRAL_BONUS",
        )

        # Contributions before and at expiry should get bonuses (using > not >= in service)
        self.assertEqual(
            distributions.count(),
            2,
            "Should have bonuses for contributions before and at expiration time",
        )

        # Verify the total amount (2 contributions of 100 each)
        expected_bonus_per_contribution = Decimal("100.00") * (
            self.service.bonus_percentage / 100
        )
        total_expected = expected_bonus_per_contribution * 2
        total_actual = sum(d.amount for d in distributions)
        self.assertEqual(
            total_actual,
            total_expected,
            f"Total bonus should be {total_expected} for 2 eligible contributions",
        )
