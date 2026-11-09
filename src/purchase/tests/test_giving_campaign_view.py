from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from purchase.models import GivingCampaign


class GivingCampaignViewTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_retrieves_campaign_by_slug(self):
        """Anyone can read a campaign's live summary by its slug."""
        # Arrange
        now = timezone.now()
        GivingCampaign.objects.create(
            slug="giving-tuesday",
            start_date=now,
            end_date=now + timedelta(days=1),
            goal_usd=Decimal(1000),
        )

        # Act
        response = self.client.get("/api/giving_campaign/giving-tuesday/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["slug"], "giving-tuesday")

    def test_returns_404_for_unknown_slug(self):
        """An unknown slug returns not found."""
        # Act
        response = self.client.get("/api/giving_campaign/unknown/")

        # Assert
        self.assertEqual(response.status_code, 404)
