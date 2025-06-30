from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from purchase.models import Balance, Fundraise, Purchase
from referral.models import ReferralSignup
from referral.services.referral_bonus_service import ReferralBonusService
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

    def test_process_fundraise_completion_creates_bonuses(self):
        """Test that referral bonuses are created for eligible referrals"""
        initial_distribution_count = Distribution.objects.count()
        initial_balance_count = Balance.objects.count()

        ReferralBonusService().process_fundraise_completion(self.fundraise)

        # Should create 2 distributions (one for referrer, one for referred user)
        self.assertEqual(Distribution.objects.count(), initial_distribution_count + 2)

        # Should create 2 balance entries (locked funds)
        self.assertEqual(Balance.objects.count(), initial_balance_count + 2)

        # Check distributions were created with correct amounts
        expected_bonus = self.contribution_amount * (
            ReferralBonusService().bonus_percentage / 100
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

        ReferralBonusService().process_fundraise_completion(self.fundraise)

        # No distributions should be created
        self.assertEqual(Distribution.objects.count(), initial_distribution_count)

        # No bonuses should be distributed for old referrals

    def test_multiple_fundraise_bonuses(self):
        """Test that bonuses are applied for multiple fundraises"""
        # Process first fundraise
        ReferralBonusService().process_fundraise_completion(self.fundraise)

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
        ReferralBonusService().process_fundraise_completion(second_fundraise)

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

        ReferralBonusService().process_fundraise_completion(self.fundraise)

        # Should only create 2 distributions for the referred user
        self.assertEqual(Distribution.objects.count(), initial_distribution_count + 2)

    def test_correct_bonus_calculation(self):
        """Test that bonus amounts are calculated correctly"""
        ReferralBonusService().process_fundraise_completion(self.fundraise)

        expected_bonus = self.contribution_amount * (
            ReferralBonusService().bonus_percentage / 100
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

        ReferralBonusService().process_fundraise_completion(self.fundraise)

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

        ReferralBonusService().process_fundraise_completion(self.fundraise)

        # Check first referral
        expected_bonus_1 = self.contribution_amount * (
            ReferralBonusService().bonus_percentage / 100
        )
        referrer_1_distribution = Distribution.objects.filter(
            recipient=self.referrer, distribution_type="REFERRAL_BONUS"
        ).first()
        self.assertEqual(referrer_1_distribution.amount, expected_bonus_1)

        # Check second referral
        expected_bonus_2 = other_contribution_amount * (
            ReferralBonusService().bonus_percentage / 100
        )
        referrer_2_distribution = Distribution.objects.filter(
            recipient=other_referrer, distribution_type="REFERRAL_BONUS"
        ).first()
        self.assertEqual(referrer_2_distribution.amount, expected_bonus_2)
