from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.serializers import RscPurchasePreviewSerializer
from user.tests.helpers import create_random_authenticated_user


class RscPurchasePreviewSerializerTests(TestCase):
    """Test RscPurchasePreviewSerializer validation"""

    def test_valid_usd_amount(self):
        """Test serializer with valid USD amount"""
        data = {"usd_amount": "100.00"}
        serializer = RscPurchasePreviewSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["usd_amount"], Decimal("100.00"))

    def test_invalid_usd_amount_negative(self):
        """Test serializer rejects negative USD amounts"""
        data = {"usd_amount": "-10.00"}
        serializer = RscPurchasePreviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("usd_amount", serializer.errors)
        self.assertIn("greater than 0", str(serializer.errors["usd_amount"]))

    def test_invalid_usd_amount_zero(self):
        """Test serializer rejects zero USD amount"""
        data = {"usd_amount": "0.00"}
        serializer = RscPurchasePreviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("usd_amount", serializer.errors)
        self.assertIn("greater than 0", str(serializer.errors["usd_amount"]))

    def test_minimum_purchase_amount(self):
        """Test serializer enforces minimum purchase amount"""
        data = {"usd_amount": "0.50"}
        serializer = RscPurchasePreviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("usd_amount", serializer.errors)
        self.assertIn(
            "Minimum purchase amount is $1.00", str(serializer.errors["usd_amount"])
        )

    def test_maximum_purchase_amount(self):
        """Test serializer enforces maximum purchase amount"""
        data = {"usd_amount": "10001.00"}
        serializer = RscPurchasePreviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("usd_amount", serializer.errors)
        self.assertIn(
            "Maximum purchase amount is $10,000.00",
            str(serializer.errors["usd_amount"]),
        )

    def test_missing_usd_amount(self):
        """Test serializer requires usd_amount"""
        data = {}
        serializer = RscPurchasePreviewSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("usd_amount", serializer.errors)


class RscPurchasePreviewViewTests(APITestCase):
    """Test RSC purchase preview endpoint"""

    def setUp(self):
        self.user = create_random_authenticated_user("test_user")
        self.client.force_authenticate(self.user)

        # Create test exchange rate
        self.exchange_rate = RscExchangeRate.objects.create(
            rate=Decimal("3.00"),
            real_rate=Decimal("3.00"),
            price_source="COIN_GECKO",
            target_currency="USD",
        )

    def test_preview_success(self):
        """Test successful USD to RSC preview"""
        response = self.client.get(
            "/api/rsc-purchase/preview/", {"usd_amount": "100.00"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["usd_amount"], "100.00")
        self.assertEqual(response.data["rsc_amount"], "33.33")  # 100 / 3 = 33.33
        self.assertEqual(response.data["exchange_rate"], "3.0")
        self.assertIn("rate_timestamp", response.data)

    def test_preview_with_different_amounts(self):
        """Test preview with various USD amounts"""
        test_cases = [
            ("1.00", "0.33"),
            ("50.00", "16.67"),
            ("999.99", "333.33"),
            ("5000.00", "1666.67"),
        ]

        for usd_amount, expected_rsc in test_cases:
            response = self.client.get(
                "/api/rsc-purchase/preview/", {"usd_amount": usd_amount}
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["usd_amount"], usd_amount)
            self.assertEqual(response.data["rsc_amount"], expected_rsc)

    def test_preview_invalid_amount(self):
        """Test preview with invalid USD amount"""
        response = self.client.get("/api/rsc-purchase/preview/", {"usd_amount": "0.50"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("usd_amount", response.data)

    def test_preview_missing_amount(self):
        """Test preview without USD amount"""
        response = self.client.get("/api/rsc-purchase/preview/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("usd_amount", response.data)

    def test_preview_requires_authentication(self):
        """Test preview endpoint requires authentication"""
        self.client.logout()
        response = self.client.get(
            "/api/rsc-purchase/preview/", {"usd_amount": "100.00"}
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_preview_exchange_rate_unavailable(self, mock_get_rate):
        """Test preview when exchange rate is unavailable"""
        mock_get_rate.side_effect = Exception("Exchange rate service unavailable")

        response = self.client.get(
            "/api/rsc-purchase/preview/", {"usd_amount": "100.00"}
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("error", response.data)
        self.assertIn("Unable to calculate RSC amount", response.data["error"])

    def test_preview_with_different_exchange_rates(self):
        """Test preview calculation with different exchange rates"""
        # Update exchange rate
        self.exchange_rate.rate = Decimal("5.00")
        self.exchange_rate.save()

        # Clear any cache
        RscExchangeRate.get_latest_exchange_rate(force_refresh=True)

        response = self.client.get(
            "/api/rsc-purchase/preview/", {"usd_amount": "100.00"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["rsc_amount"], "20.00")  # 100 / 5 = 20
        self.assertEqual(response.data["exchange_rate"], "5.0")
