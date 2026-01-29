from django.test import TestCase

from funding_dashboard.services import DashboardService
from user.tests.helpers import create_random_authenticated_user


class TestDashboardService(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("funder")

    def test_get_overview_returns_dict(self):
        # Arrange
        service = DashboardService(self.user)

        # Act
        result = service.get_overview()

        # Assert
        self.assertIsInstance(result, dict)

    def test_get_grant_overview_returns_dict(self):
        # Arrange
        service = DashboardService(self.user)

        # Act
        result = service.get_grant_overview(grant_id=1)

        # Assert
        self.assertIsInstance(result, dict)
