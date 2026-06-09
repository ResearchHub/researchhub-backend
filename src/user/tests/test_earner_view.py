from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework.test import APITestCase

from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.tests.helpers import create_random_authenticated_user, create_user


class EarnerViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("earner_views", moderator=True)
        self.recipient = create_user(email="earner-recipient@test.com")
        self.funder = create_user(email="earner-funder@test.com")
        self.ct = ContentType.objects.get_for_model(FundingActivity)

    def _create_recipient_activity(self, source_type, total_amount, total_usd_cents):
        activity = FundingActivity.objects.create(
            funder=self.funder,
            source_type=source_type,
            total_amount=Decimal(str(total_amount)),
            total_usd_cents=total_usd_cents,
            activity_date=timezone.now(),
            source_content_type=self.ct,
            source_object_id=FundingActivity.objects.count() + 1,
        )
        FundingActivityRecipient.objects.create(
            activity=activity,
            recipient_user=self.recipient,
            amount=Decimal(str(total_amount)),
            amount_usd_cents=total_usd_cents,
        )
        return activity

    def test_earning_overview_requires_authentication(self):
        # Arrange
        self.client.logout()

        # Act
        response = self.client.get("/api/user/earning_overview/")

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_earning_overview_ignores_user_id_for_non_moderator(self):
        # Arrange
        self._create_recipient_activity(
            FundingActivity.BOUNTY_PAYOUT, total_amount="30", total_usd_cents=1500
        )
        other_user = create_random_authenticated_user("other_earner")
        regular_user = create_random_authenticated_user("regular_earner")
        self.client.force_authenticate(regular_user)

        # Act
        response = self.client.get(
            "/api/user/earning_overview/", {"user_id": self.recipient.id}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_earned"]["rsc"], 0.0)

    def test_earning_overview_moderator_can_use_user_id(self):
        # Arrange
        self._create_recipient_activity(
            FundingActivity.TIP_REVIEW, total_amount="20", total_usd_cents=1000
        )
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(
            "/api/user/earning_overview/", {"user_id": self.recipient.id}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_earned"]["rsc"], 20.0)
        self.assertEqual(response.data["total_earned"]["rsc_usd_snapshot"], 10.0)

    def test_earning_overview_moderator_invalid_user_id_returns_404(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(
            "/api/user/earning_overview/", {"user_id": 999999}
        )

        # Assert
        self.assertEqual(response.status_code, 404)

    def test_earning_overview_returns_total_and_by_source(self):
        # Arrange
        self._create_recipient_activity(
            FundingActivity.FUNDRAISE_PAYOUT, total_amount="100", total_usd_cents=5000
        )
        self._create_recipient_activity(
            FundingActivity.USD_FUNDRAISE_PAYOUT,
            total_amount="20",
            total_usd_cents=1000,
        )
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(
            "/api/user/earning_overview/", {"user_id": self.recipient.id}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["total_earned"],
            {"rsc": 120.0, "rsc_usd_snapshot": 50.0, "usd": 10.0},
        )
        self.assertEqual(
            response.data["by_source"][FundingActivity.FUNDRAISE_PAYOUT],
            {"rsc": 100.0, "rsc_usd_snapshot": 50.0, "usd": 0.0},
        )
        self.assertEqual(
            response.data["by_source"][FundingActivity.USD_FUNDRAISE_PAYOUT],
            {"rsc": 20.0, "rsc_usd_snapshot": 0.0, "usd": 10.0},
        )

    def test_earning_overview_empty_user_returns_zeros(self):
        # Arrange
        empty_user = create_random_authenticated_user("empty_earner")
        self.client.force_authenticate(empty_user)

        # Act
        response = self.client.get("/api/user/earning_overview/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["total_earned"],
            {"rsc": 0.0, "rsc_usd_snapshot": 0.0, "usd": 0.0},
        )
        self.assertEqual(response.data["by_source"], {})
