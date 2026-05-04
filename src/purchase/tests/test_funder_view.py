from decimal import Decimal

from rest_framework.test import APITestCase

from purchase.models import Grant, RscExchangeRate
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC_TYPE,
)
from user.tests.helpers import create_random_authenticated_user


class FunderViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("funder_views", moderator=True)
        RscExchangeRate.objects.create(
            rate=0.5, real_rate=0.5, price_source="COIN_GECKO", target_currency="USD"
        )

    def test_funding_overview_allows_unauthenticated(self):
        self.client.logout()

        response = self.client.get(
            "/api/funder/funding_overview/", {"user_id": self.user.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)
        self.assertIn("supported_institutions", response.data)

    def test_funding_overview_returns_200(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/funder/funding_overview/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)
        self.assertIn("supported_institutions", response.data)

    def test_funding_impact_requires_authentication(self):
        self.client.logout()

        response = self.client.get("/api/funder/funding_impact/")

        self.assertEqual(response.status_code, 401)

    def test_funding_impact_returns_200(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/funder/funding_impact/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)

    def test_grant_overview_requires_authentication(self):
        # Arrange
        self.client.logout()

        # Act
        response = self.client.get("/api/funder/999/grant_overview/")

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_grant_overview_returns_404_for_missing_grant(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get("/api/funder/999999/grant_overview/")

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_grant_overview_returns_200(self):
        # Arrange
        self.client.force_authenticate(self.user)
        grant_post = create_post(created_by=self.user, document_type=GRANT_DOC_TYPE)
        Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=Decimal("10000"),
            status=Grant.OPEN,
        )

        # Act
        response = self.client.get(f"/api/funder/{grant_post.id}/grant_overview/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)
