import uuid
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
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

        self.assertEqual(len(data), 2)

        # Find referred_user1 in the response
        user1_data = next(d for d in data if d["user_id"] == self.referred_user1.id)
        self.assertEqual(user1_data["total_funded"], 1000.0)
        self.assertEqual(user1_data["referral_bonus_earned"], 100.0)
        self.assertTrue(user1_data["is_active_funder"])

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
