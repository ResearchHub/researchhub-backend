import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from hub.models import Hub
from purchase.models import Purchase
from purchase.related_models.balance_model import Balance
from purchase.related_models.fundraise_model import Fundraise
from referral.models import ReferralSignup
from reputation.related_models.distribution import Distribution
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User


class ReferralMetricsAPITest(TestCase):
    """Test cases for referral metrics API endpoints."""

    def setUp(self):
        self.client = APIClient()

        # Create test users
        self.referrer = User.objects.create_user(
            username="referrer", email="referrer@test.com", password=uuid.uuid4().hex
        )

        self.referred_user1 = User.objects.create_user(
            username="referred1", email="referred1@test.com", password=uuid.uuid4().hex
        )

        self.referred_user2 = User.objects.create_user(
            username="referred2", email="referred2@test.com", password=uuid.uuid4().hex
        )

        self.admin_user = User.objects.create_superuser(
            username="admin", email="admin@test.com", password=uuid.uuid4().hex
        )

        # Create referral signups
        self.referral1 = ReferralSignup.objects.create(
            referrer=self.referrer, referred=self.referred_user1
        )

        self.referral2 = ReferralSignup.objects.create(
            referrer=self.referrer, referred=self.referred_user2
        )

        # Create test hub and unified document for fundraise
        self.hub = Hub.objects.create(name="Test Hub")

        # Create unified document
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.unified_document.hubs.add(self.hub)

        # Create a fundraise
        self.fundraise = Fundraise.objects.create(
            created_by=self.referrer,
            unified_document=self.unified_document,
            goal_amount=10000,
            goal_currency="USD",
            status="OPEN",
        )

        # Create purchases (contributions)
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)

        self.purchase1 = Purchase.objects.create(
            user=self.referred_user1,
            content_type=fundraise_content_type,
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount="1000",
        )

        self.purchase2 = Purchase.objects.create(
            user=self.referrer,
            content_type=fundraise_content_type,
            object_id=self.fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            paid_status=Purchase.PAID,
            amount="5000",
        )

        # Create referral bonus distributions
        self.distribution1 = Distribution.objects.create(
            recipient=self.referrer,
            distribution_type="REFERRAL_BONUS",
            amount=Decimal("100"),  # 10% of referred user's contribution
            distributed_status=Distribution.DISTRIBUTED,
        )

        self.distribution2 = Distribution.objects.create(
            recipient=self.referred_user1,
            distribution_type="REFERRAL_BONUS",
            amount=Decimal("100"),
            distributed_status=Distribution.DISTRIBUTED,
        )

        # Create locked balances linked to distributions
        distribution_content_type = ContentType.objects.get_for_model(Distribution)

        self.balance1 = Balance.objects.create(
            user=self.referrer,
            content_type=distribution_content_type,
            object_id=self.distribution1.id,
            amount="100",
            is_locked=True,
            lock_type="REFERRAL_BONUS",
        )

        self.balance2 = Balance.objects.create(
            user=self.referred_user1,
            content_type=distribution_content_type,
            object_id=self.distribution2.id,
            amount="100",
            is_locked=True,
            lock_type="REFERRAL_BONUS",
        )

    def test_get_my_referral_metrics(self):
        """Test getting current user's referral metrics."""
        self.client.force_authenticate(user=self.referrer)

        url = reverse("referral:referral-metrics-my-metrics")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check structure
        self.assertIn("network_funding_power", data)
        self.assertIn("referral_activity", data)
        self.assertIn("your_funding_credits", data)
        self.assertIn("network_earned_credits", data)

        # Check network funding power
        self.assertEqual(
            data["network_funding_power"]["breakdown"]["direct_funding"], 5000.0
        )
        self.assertEqual(
            data["network_funding_power"]["breakdown"]["network_funding"], 1000.0
        )

        # Check referral activity
        self.assertEqual(data["referral_activity"]["funders_invited"], 2)
        self.assertEqual(data["referral_activity"]["active_funders"], 1)

        # Check funding credits
        self.assertEqual(data["your_funding_credits"]["available"], 100.0)
        self.assertEqual(data["your_funding_credits"]["total_earned"], 100.0)

    def test_get_network_details(self):
        """Test getting detailed network information."""
        self.client.force_authenticate(user=self.referrer)

        url = reverse("referral:referral-metrics-network-details")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check pagination structure
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("results", data)

        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 2)

        # Find referred_user1 in the response
        user1_data = next(
            d for d in data["results"] if d["user_id"] == self.referred_user1.id
        )
        self.assertEqual(user1_data["total_funded"], 1000.0)
        self.assertEqual(user1_data["referral_bonus_earned"], 100.0)
        self.assertTrue(user1_data["is_active_funder"])

        # Check new fields
        self.assertIn("full_name", user1_data)
        self.assertIn("author_id", user1_data)
        self.assertIn("profile_image", user1_data)
        self.assertEqual(user1_data["full_name"], self.referred_user1.full_name())
        # Author profile may exist or not depending on test database state
        self.assertTrue("author_id" in user1_data)
        self.assertIsNone(user1_data["profile_image"])  # No profile image set in test

    def test_get_network_details_with_pagination(self):
        """
        Test network details endpoint with pagination parameters.
        """
        # Arrange
        self.client.force_authenticate(user=self.referrer)

        # Test with page_size=1
        url = reverse("referral:referral-metrics-network-details")
        response = self.client.get(url, {"page_size": 1})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 1)
        self.assertIsNotNone(data["next"])
        self.assertIsNone(data["previous"])

        # Test page 2
        response = self.client.get(url, {"page": 2, "page_size": 1})
        data = response.json()

        self.assertEqual(len(data["results"]), 1)
        self.assertIsNone(data["next"])
        self.assertIsNotNone(data["previous"])

    def test_admin_can_view_other_user_metrics(self):
        """Test that admin can view any user's referral metrics."""
        self.client.force_authenticate(user=self.admin_user)

        url = reverse(
            "referral:referral-metrics-user-metrics", kwargs={"pk": self.referrer.id}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["user_id"], self.referrer.id)
        self.assertEqual(data["username"], self.referrer.username)
        self.assertIn("metrics", data)

    def test_non_admin_cannot_view_other_user_metrics(self):
        """Test that non-admin users cannot view other users' metrics."""
        self.client.force_authenticate(user=self.referred_user1)

        url = reverse(
            "referral:referral-metrics-user-metrics", kwargs={"pk": self.referrer.id}
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_aggregate_metrics_admin_only(self):
        """Test that aggregate metrics are only accessible to admins."""
        # Test as regular user
        self.client.force_authenticate(user=self.referrer)
        url = reverse("referral:aggregate-referral-metrics-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Test as admin
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("total_referrals", data)
        self.assertIn("active_referrals", data)
        self.assertIn("total_bonuses_distributed", data)
        self.assertIn("top_referrers", data)

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated users cannot access referral metrics."""
        url = reverse("referral:referral-metrics-my-metrics")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_network_details_includes_expiration_fields(self):
        """Test that network details include expiration date fields."""
        self.client.force_authenticate(user=self.referrer)

        url = reverse("referral:referral-metrics-network-details")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check that each referred user has expiration date fields
        self.assertTrue(len(data["results"]) > 0)
        for user_data in data["results"]:
            self.assertIn("referral_bonus_expiration_date", user_data)
            self.assertIn("is_referral_bonus_expired", user_data)
            # Just verify these are valid datetime/boolean, not the calculation
            self.assertIsInstance(user_data["referral_bonus_expiration_date"], str)
            self.assertIsInstance(user_data["is_referral_bonus_expired"], bool)

    def test_user_referral_info_included_when_referred(self):
        """Test that user's own referral info is included when they were referred."""
        # Create a user who was referred by someone
        referring_user = User.objects.create_user(
            username="referring_user",
            email="referring@test.com",
            password=uuid.uuid4().hex,
        )
        referred_user = User.objects.create_user(
            username="referred_user",
            email="referred@test.com",
            password=uuid.uuid4().hex,
        )

        # Create referral signup
        ReferralSignup.objects.create(referrer=referring_user, referred=referred_user)

        self.client.force_authenticate(user=referred_user)

        url = reverse("referral:referral-metrics-my-metrics")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check that referral info is included
        self.assertIn("your_referral_info", data)
        referral_info = data["your_referral_info"]

        # Check that referrer details are included
        self.assertIn("referrer", referral_info)
        referrer_details = referral_info["referrer"]

        # Check referrer fields
        self.assertEqual(referrer_details["username"], referring_user.username)
        self.assertEqual(referrer_details["user_id"], referring_user.id)
        self.assertIn("full_name", referrer_details)
        self.assertIn("author_id", referrer_details)
        self.assertIn("profile_image", referrer_details)
        self.assertIn("total_funded", referrer_details)
        self.assertIn("referral_bonus_earned", referrer_details)
        self.assertIn("is_active_funder", referrer_details)

        # Check referral timing fields
        self.assertIn("referral_signup_date", referral_info)
        self.assertIn("referral_bonus_expiration_date", referral_info)
        self.assertIn("is_referral_bonus_expired", referral_info)

        # Verify expiration date calculation
        signup_date = timezone.datetime.fromisoformat(
            referral_info["referral_signup_date"].replace("Z", "+00:00")
        )
        expiration_date = timezone.datetime.fromisoformat(
            referral_info["referral_bonus_expiration_date"].replace("Z", "+00:00")
        )

        expected_expiration = signup_date + timedelta(days=30 * 6)
        self.assertAlmostEqual(
            expiration_date.timestamp(), expected_expiration.timestamp(), delta=60
        )

    def test_user_referral_info_not_included_when_not_referred(self):
        """Test that user's referral info is not included when they weren't referred."""
        # Create a user who was NOT referred by anyone
        independent_user = User.objects.create_user(
            username="independent",
            email="independent@test.com",
            password=uuid.uuid4().hex,
        )

        self.client.force_authenticate(user=independent_user)

        url = reverse("referral:referral-metrics-my-metrics")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check that referral info is None when user wasn't referred
        self.assertIn("your_referral_info", data)
        self.assertIsNone(data["your_referral_info"])

    def test_monitoring_endpoint_moderator_access(self):
        """Test that moderators can access the monitoring endpoint."""
        # Create a moderator user
        moderator = User.objects.create_user(
            username="moderator",
            email="moderator@test.com",
            password=uuid.uuid4().hex,
        )
        moderator.moderator = True
        moderator.save()

        self.client.force_authenticate(user=moderator)

        url = reverse("referral:referral-monitoring-monitor")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check pagination structure
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertEqual(data["count"], 2)  # Should have 2 referrals from setUp

        # Check first referral structure
        referral = data["results"][0]
        self.assertIn("id", referral)
        self.assertIn("signup_date", referral)
        self.assertIn("referral_bonus_expiration_date", referral)
        self.assertIn("is_referral_bonus_expired", referral)
        self.assertIn("referred_user", referral)
        self.assertIn("referrer", referral)

        # Check referred_user fields
        referred_user = referral["referred_user"]
        self.assertIn("user_id", referred_user)
        self.assertIn("username", referred_user)
        self.assertIn("full_name", referred_user)
        self.assertIn("author_id", referred_user)
        self.assertIn("profile_image", referred_user)
        self.assertIn("signup_date", referred_user)
        self.assertIn("referral_bonus_expiration_date", referred_user)
        self.assertIn("is_referral_bonus_expired", referred_user)
        self.assertIn("total_funded", referred_user)
        self.assertIn("referral_bonus_earned", referred_user)
        self.assertIn("is_active_funder", referred_user)

        # Check referrer fields
        referrer = referral["referrer"]
        self.assertIn("id", referrer)
        self.assertIn("username", referrer)
        self.assertIn("full_name", referrer)
        self.assertIn("email", referrer)
        self.assertIn("author_id", referrer)
        self.assertIn("profile_image", referrer)
        self.assertIn("total_credits_earned", referrer)

    def test_monitoring_endpoint_regular_user_denied(self):
        """Test that regular users cannot access the monitoring endpoint."""
        self.client.force_authenticate(user=self.referrer)

        url = reverse("referral:referral-monitoring-monitor")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_monitoring_endpoint_data_structure(self):
        """Test that monitoring endpoint returns data with correct structure."""
        moderator = User.objects.create_user(
            username="moderator3",
            email="moderator3@test.com",
            password=uuid.uuid4().hex,
        )
        moderator.moderator = True
        moderator.save()

        self.client.force_authenticate(user=moderator)

        url = reverse("referral:referral-monitoring-monitor")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check that we have results
        self.assertTrue(len(data["results"]) > 0)

        # Check structure of first result
        first_referral = data["results"][0]

        # Check top-level fields
        self.assertIn("id", first_referral)
        self.assertIn("signup_date", first_referral)
        self.assertIn("referral_bonus_expiration_date", first_referral)
        self.assertIn("is_referral_bonus_expired", first_referral)
        self.assertIn("referred_user", first_referral)
        self.assertIn("referrer", first_referral)

        # Check referred_user has required fields
        referred_user = first_referral["referred_user"]
        required_referred_fields = [
            "user_id",
            "username",
            "full_name",
            "author_id",
            "profile_image",
            "signup_date",
            "referral_bonus_expiration_date",
            "is_referral_bonus_expired",
            "total_funded",
            "referral_bonus_earned",
            "is_active_funder",
        ]
        for field in required_referred_fields:
            self.assertIn(field, referred_user, f"Missing field: {field}")

        # Check referrer has required fields
        referrer = first_referral["referrer"]
        required_referrer_fields = [
            "id",
            "username",
            "full_name",
            "email",
            "author_id",
            "profile_image",
            "total_credits_earned",
        ]
        for field in required_referrer_fields:
            self.assertIn(field, referrer, f"Missing field: {field}")

    def test_monitoring_endpoint_pagination(self):
        """Test that monitoring endpoint pagination works correctly."""
        moderator = User.objects.create_user(
            username="moderator4",
            email="moderator4@test.com",
            password=uuid.uuid4().hex,
        )
        moderator.moderator = True
        moderator.save()

        self.client.force_authenticate(user=moderator)

        # Test with page_size=1
        url = reverse("referral:referral-monitoring-monitor")
        response = self.client.get(url, {"page_size": 1})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["results"]), 1)
        self.assertIsNotNone(data["next"])
        self.assertIsNone(data["previous"])

        # Test page 2
        response = self.client.get(url, {"page": 2, "page_size": 1})
        data = response.json()

        self.assertEqual(len(data["results"]), 1)
        self.assertIsNone(data["next"])
        self.assertIsNotNone(data["previous"])
