from rest_framework.test import APITestCase

from purchase.models import RscExchangeRate
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

    def test_funding_overview_returns_200(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/funder/funding_overview/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)

    def test_funding_impact_requires_authentication(self):
        self.client.logout()

        response = self.client.get("/api/funder/funding_impact/")

        self.assertEqual(response.status_code, 401)

    def test_funding_impact_returns_200(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/funder/funding_impact/")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)
