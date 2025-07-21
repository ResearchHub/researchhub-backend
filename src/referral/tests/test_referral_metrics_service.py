import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referral.models import ReferralSignup
from referral.services.referral_metrics_service import ReferralMetricsService
from user.models import User


class ReferralMetricsServiceTest(TestCase):
    """Test cases for ReferralMetricsService methods."""

    def setUp(self):
        # Create test users
        self.referrer = User.objects.create_user(
            username="referrer", email="referrer@test.com", password=uuid.uuid4().hex
        )

        self.referred = User.objects.create_user(
            username="referred", email="referred@test.com", password=uuid.uuid4().hex
        )

        # Create service instance
        self.service = ReferralMetricsService(self.referrer)

    def test_calculate_expiration_date(self):
        """Test expiration date calculation is 6 months from signup."""
        signup_date = timezone.now()
        expiration_date = self.service._calculate_expiration_date(signup_date)

        expected_expiration = signup_date + timedelta(days=30 * 6)

        # Allow small time difference for test execution
        self.assertAlmostEqual(
            expiration_date.timestamp(),
            expected_expiration.timestamp(),
            delta=1,  # 1 second tolerance
        )

    def test_is_referral_expired_recent_signup(self):
        """Test that recent signups are not marked as expired."""
        # Recent signup (1 day ago)
        recent_signup_date = timezone.now() - timedelta(days=1)
        is_expired = self.service._is_referral_expired(recent_signup_date)

        self.assertFalse(is_expired)

    def test_is_referral_expired_old_signup(self):
        """Test that old signups are marked as expired."""
        # Old signup (7 months ago)
        old_signup_date = timezone.now() - timedelta(days=30 * 7)
        is_expired = self.service._is_referral_expired(old_signup_date)

        self.assertTrue(is_expired)

    def test_is_referral_expired_exact_boundary(self):
        """Test expiration at exactly 6 months."""
        # Exactly 6 months ago (plus 1 minute to ensure it's expired)
        boundary_date = timezone.now() - timedelta(days=30 * 6, minutes=1)
        is_expired = self.service._is_referral_expired(boundary_date)

        self.assertTrue(is_expired)

        # Just under 6 months ago
        not_quite_expired = timezone.now() - timedelta(days=30 * 6 - 1)
        is_expired = self.service._is_referral_expired(not_quite_expired)

        self.assertFalse(is_expired)

    def test_get_user_referral_info_when_referred(self):
        """Test getting user's own referral info when they were referred."""
        # Create referral relationship
        referral = ReferralSignup.objects.create(
            referrer=self.referrer, referred=self.referred
        )

        # Test with referred user
        referred_service = ReferralMetricsService(self.referred)
        referral_info = referred_service._get_user_referral_info()

        self.assertIsNotNone(referral_info)
        self.assertIn("referrer", referral_info)
        self.assertEqual(referral_info["referrer"]["username"], self.referrer.username)
        self.assertIn("referral_signup_date", referral_info)
        self.assertIn("referral_bonus_expiration_date", referral_info)
        self.assertIn("is_referral_bonus_expired", referral_info)
        self.assertFalse(referral_info["is_referral_bonus_expired"])

    def test_get_user_referral_info_when_not_referred(self):
        """Test getting user's referral info when they weren't referred."""
        # User with no referral
        independent_user = User.objects.create_user(
            username="independent",
            email="independent@test.com",
            password=uuid.uuid4().hex,
        )

        independent_service = ReferralMetricsService(independent_user)
        referral_info = independent_service._get_user_referral_info()

        self.assertIsNone(referral_info)

    def test_get_user_referral_info_with_expired_bonus(self):
        """Test referral info for expired bonus period."""
        # Create old referral
        referral = ReferralSignup.objects.create(
            referrer=self.referrer, referred=self.referred
        )

        # Update signup date to be old
        old_date = timezone.now() - timedelta(days=30 * 7)
        ReferralSignup.objects.filter(id=referral.id).update(signup_date=old_date)

        referred_service = ReferralMetricsService(self.referred)
        referral_info = referred_service._get_user_referral_info()

        self.assertIsNotNone(referral_info)
        self.assertTrue(referral_info["is_referral_bonus_expired"])

        # Check expiration date is in the past
        expiration_date = referral_info["referral_bonus_expiration_date"]
        self.assertTrue(timezone.now() > expiration_date)

    def test_comprehensive_metrics_includes_referral_info(self):
        """Test that comprehensive metrics include user's referral info when applicable."""
        # Create referral for the user
        referring_user = User.objects.create_user(
            username="referring", email="referring@test.com", password=uuid.uuid4().hex
        )

        ReferralSignup.objects.create(referrer=referring_user, referred=self.referrer)

        metrics = self.service.get_comprehensive_metrics()

        # Should include referral info
        self.assertIn("your_referral_info", metrics)
        self.assertIn("referrer", metrics["your_referral_info"])
        self.assertEqual(
            metrics["your_referral_info"]["referrer"]["username"],
            referring_user.username,
        )

    def test_comprehensive_metrics_no_referral_info(self):
        """Test that comprehensive metrics don't include referral info when not referred."""
        # User not referred by anyone
        metrics = self.service.get_comprehensive_metrics()

        # Should not include referral info
        self.assertNotIn("your_referral_info", metrics)

    def test_network_details_includes_expiration_dates(self):
        """Test that network details include expiration dates for each referred user."""
        # Create some referrals
        for i in range(3):
            referred_user = User.objects.create_user(
                username=f"referred_{i}",
                email=f"referred_{i}@test.com",
                password=uuid.uuid4().hex,
            )
            ReferralSignup.objects.create(
                referrer=self.referrer, referred=referred_user
            )

        network_details = self.service.get_referral_network_details()

        self.assertEqual(len(network_details), 3)

        for user_detail in network_details:
            self.assertIn("referral_bonus_expiration_date", user_detail)
            self.assertIn("is_referral_bonus_expired", user_detail)
            self.assertIn("signup_date", user_detail)

            # Verify expiration is 6 months after signup
            signup_date = user_detail["signup_date"]
            expiration_date = user_detail["referral_bonus_expiration_date"]
            expected_expiration = signup_date + timedelta(days=30 * 6)

            self.assertAlmostEqual(
                expiration_date.timestamp(), expected_expiration.timestamp(), delta=1
            )

    def test_prepare_monitoring_data_accuracy(self):
        """Test that prepare_monitoring_data returns accurate financial data."""
        from django.contrib.contenttypes.models import ContentType

        from hub.models import Hub
        from purchase.models import Purchase
        from purchase.related_models.balance_model import Balance
        from purchase.related_models.fundraise_model import Fundraise
        from reputation.related_models.distribution import Distribution
        from researchhub_document.models import ResearchhubUnifiedDocument

        # Create test data
        referred_user = User.objects.create_user(
            username="test_referred",
            email="test_referred@test.com",
            password=uuid.uuid4().hex,
        )

        referral_signup = ReferralSignup.objects.create(
            referrer=self.referrer, referred=referred_user
        )

        # Create test hub and unified document for fundraise
        hub = Hub.objects.create(name="Test Hub")
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        unified_document.hubs.add(hub)

        # Create a fundraise
        fundraise = Fundraise.objects.create(
            created_by=self.referrer,
            unified_document=unified_document,
            goal_amount=10000,
            goal_currency="USD",
            status="OPEN",
        )

        # Create purchases
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)

        Purchase.objects.create(
            user=referred_user,
            content_type=fundraise_content_type,
            object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount="1000",
        )

        # Create referral bonus distributions
        distribution_referrer = Distribution.objects.create(
            recipient=self.referrer,
            distribution_type="REFERRAL_BONUS",
            amount=Decimal("100"),
            distributed_status=Distribution.DISTRIBUTED,
        )

        distribution_referred = Distribution.objects.create(
            recipient=referred_user,
            distribution_type="REFERRAL_BONUS",
            amount=Decimal("50"),
            distributed_status=Distribution.DISTRIBUTED,
        )

        # Test prepare_monitoring_data
        monitoring_data = self.service.prepare_monitoring_data(referral_signup)

        # Check structure
        self.assertIn("id", monitoring_data)
        self.assertIn("signup_date", monitoring_data)
        self.assertIn("referral_bonus_expiration_date", monitoring_data)
        self.assertIn("is_referral_bonus_expired", monitoring_data)
        self.assertIn("referred_user", monitoring_data)
        self.assertIn("referrer", monitoring_data)

        # Check referred user data accuracy
        referred_data = monitoring_data["referred_user"]
        self.assertEqual(referred_data["user_id"], referred_user.id)
        self.assertEqual(referred_data["username"], referred_user.username)
        self.assertEqual(referred_data["total_funded"], 1000.0)
        self.assertEqual(referred_data["referral_bonus_earned"], 50.0)
        self.assertTrue(referred_data["is_active_funder"])

        # Check referrer data accuracy
        referrer_data = monitoring_data["referrer"]
        self.assertEqual(referrer_data["id"], self.referrer.id)
        self.assertEqual(referrer_data["username"], self.referrer.username)
        self.assertEqual(referrer_data["total_credits_earned"], 100.0)

        # Check expiration date calculation
        expiration_date = monitoring_data["referral_bonus_expiration_date"]
        expected_expiration = referral_signup.signup_date + timedelta(days=30 * 6)
        self.assertAlmostEqual(
            expiration_date.timestamp(),
            expected_expiration.timestamp(),
            delta=1,
        )

    def test_prepare_monitoring_data_with_expired_referral(self):
        """Test monitoring data for expired referrals."""
        from django.contrib.contenttypes.models import ContentType

        from hub.models import Hub
        from purchase.models import Purchase
        from purchase.related_models.fundraise_model import Fundraise
        from reputation.related_models.distribution import Distribution
        from researchhub_document.models import ResearchhubUnifiedDocument

        # Create a referral that's over 6 months old
        old_referred = User.objects.create_user(
            username="old_referred",
            email="old_referred@test.com",
            password=uuid.uuid4().hex,
        )

        old_referral = ReferralSignup.objects.create(
            referrer=self.referrer, referred=old_referred
        )

        # Manually update the signup date to be 7 months ago
        old_date = timezone.now() - timedelta(days=30 * 7)
        ReferralSignup.objects.filter(id=old_referral.id).update(signup_date=old_date)
        old_referral.refresh_from_db()

        # Test monitoring data
        monitoring_data = self.service.prepare_monitoring_data(old_referral)

        # Should be marked as expired
        self.assertTrue(monitoring_data["is_referral_bonus_expired"])
        self.assertTrue(monitoring_data["referred_user"]["is_referral_bonus_expired"])

        # Check that the expiration date is in the past
        expiration_date = monitoring_data["referral_bonus_expiration_date"]
        self.assertTrue(timezone.now() > expiration_date)
