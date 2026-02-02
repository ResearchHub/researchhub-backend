from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from purchase.models import EndaomentAccount
from purchase.views import EndaomentViewSet

User = get_user_model()


class TestEndaomentViewSet(TestCase):
    """
    Tests for the `EndaomentViewSet`.
    """

    def setUp(self):
        self.factory = APIRequestFactory()
        self.service_mock = Mock()
        self.user = User.objects.create_user(username="user1", password="password1")
        self.funds_view = EndaomentViewSet.as_view({"get": "funds"})

    def test_funds_returns_list(self):
        """
        Test that authenticated user gets their funds list.
        """
        # Arrange
        self.service_mock.get_user_funds.return_value = [
            {"id": "fund-1", "name": "My Fund", "usdcBalance": "1000000"}
        ]

        request = self.factory.get("/api/endaoment/funds/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.funds_view(request, service=self.service_mock)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], "fund-1")
        self.service_mock.get_user_funds.assert_called_once_with(self.user)

    def test_funds_without_endaoment_account_returns_404(self):
        """
        Test that a user without an Endaoment connection gets 404.
        """
        # Arrange
        self.service_mock.get_user_funds.side_effect = EndaomentAccount.DoesNotExist(
            "No connection"
        )

        request = self.factory.get("/api/endaoment/funds/")
        force_authenticate(request, user=self.user)

        # Act
        response = self.funds_view(request, service=self.service_mock)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["detail"], "No Endaoment connection found.")

    def test_funds_unauthenticated_returns_401_or_403(self):
        """
        Test that unauthenticated request is rejected.
        """
        # Arrange
        request = self.factory.get("/api/endaoment/funds/")

        # Act
        response = self.funds_view(request, service=self.service_mock)

        # Assert
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
