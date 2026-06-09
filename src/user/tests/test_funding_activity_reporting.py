from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.services.funding_activity_reporting import (
    EARNER_SOURCE_TYPES,
    FundingActivityReportingService,
)
from user.tests.helpers import create_user

_ZERO_BREAKDOWN = {"rsc": 0.0, "rsc_usd_snapshot": 0.0, "usd": 0.0}


class FundingActivityReportingTests(TestCase):
    def setUp(self):
        self.funder = create_user(email="report-funder@test.com")
        self.recipient = create_user(email="report-recipient@test.com")
        self.ct = ContentType.objects.get_for_model(FundingActivity)

    def _create_activity(
        self,
        source_type,
        total_amount,
        total_usd_cents,
        recipient_amount=None,
        recipient_amount_usd_cents=None,
    ):
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
            amount=Decimal(
                str(recipient_amount if recipient_amount is not None else total_amount)
            ),
            amount_usd_cents=(
                recipient_amount_usd_cents
                if recipient_amount_usd_cents is not None
                else total_usd_cents
            ),
        )
        return activity

    def test_earnings_for_user_rsc_native_row(self):
        """RSC-origin row: rsc from amount, rsc_usd_snapshot from usd_cents."""
        # Arrange
        self._create_activity(
            FundingActivity.BOUNTY_PAYOUT, total_amount="50", total_usd_cents=2500
        )

        # Act
        result = FundingActivityReportingService.earnings_for_user(self.recipient.id)

        # Assert
        self.assertEqual(
            result["total_earned"],
            {"rsc": 50.0, "rsc_usd_snapshot": 25.0, "usd": 0.0},
        )
        self.assertEqual(
            result["by_source"][FundingActivity.BOUNTY_PAYOUT],
            {"rsc": 50.0, "rsc_usd_snapshot": 25.0, "usd": 0.0},
        )

    def test_earnings_for_user_usd_native_row(self):
        """USD-origin row: rsc from calculated amount, usd from usd_cents."""
        # Arrange
        self._create_activity(
            FundingActivity.USD_FUNDRAISE_PAYOUT,
            total_amount="200",
            total_usd_cents=10000,
        )

        # Act
        result = FundingActivityReportingService.earnings_for_user(self.recipient.id)

        # Assert
        self.assertEqual(
            result["total_earned"],
            {"rsc": 200.0, "rsc_usd_snapshot": 0.0, "usd": 100.0},
        )

    def test_earnings_for_user_mixed_rows(self):
        """Mixed sources sum each leg without rate math."""
        # Arrange
        self._create_activity(
            FundingActivity.TIP_REVIEW, total_amount="10", total_usd_cents=500
        )
        self._create_activity(
            FundingActivity.USD_FUNDRAISE_PAYOUT,
            total_amount="40",
            total_usd_cents=2000,
        )

        # Act
        result = FundingActivityReportingService.earnings_for_user(self.recipient.id)

        # Assert
        self.assertEqual(
            result["total_earned"],
            {"rsc": 50.0, "rsc_usd_snapshot": 5.0, "usd": 20.0},
        )
        self.assertEqual(len(result["by_source"]), 2)

    def test_earnings_for_user_by_source_breakdown(self):
        # Arrange
        self._create_activity(
            FundingActivity.BOUNTY_PAYOUT, total_amount="30", total_usd_cents=1500
        )
        self._create_activity(
            FundingActivity.USD_FUNDRAISE_PAYOUT,
            total_amount="60",
            total_usd_cents=3000,
        )

        # Act
        result = FundingActivityReportingService.earnings_for_user(self.recipient.id)

        # Assert
        self.assertEqual(
            result["by_source"][FundingActivity.BOUNTY_PAYOUT],
            {"rsc": 30.0, "rsc_usd_snapshot": 15.0, "usd": 0.0},
        )
        self.assertEqual(
            result["by_source"][FundingActivity.USD_FUNDRAISE_PAYOUT],
            {"rsc": 60.0, "rsc_usd_snapshot": 0.0, "usd": 30.0},
        )

    def test_funding_for_user(self):
        # Arrange
        self._create_activity(
            FundingActivity.TIP_DOCUMENT, total_amount="25", total_usd_cents=1250
        )

        # Act
        result = FundingActivityReportingService.funding_for_user(self.funder.id)

        # Assert
        self.assertEqual(result, {"rsc": 25.0, "rsc_usd_snapshot": 12.5, "usd": 0.0})

    def test_earnings_for_user_totals(self):
        # Arrange
        self._create_activity(
            FundingActivity.FUNDRAISE_PAYOUT, total_amount="100", total_usd_cents=5000
        )
        self._create_activity(
            FundingActivity.USD_FUNDRAISE_PAYOUT,
            total_amount="20",
            total_usd_cents=1000,
        )

        # Act
        result = FundingActivityReportingService.earnings_for_user(self.recipient.id)

        # Assert
        self.assertEqual(
            result["total_earned"],
            {"rsc": 120.0, "rsc_usd_snapshot": 50.0, "usd": 10.0},
        )
        self.assertEqual(len(result["by_source"]), 2)

    def test_earnings_for_user_excludes_fee_by_default(self):
        # Arrange
        self._create_activity(FundingActivity.FEE, total_amount="5", total_usd_cents=250)

        # Act
        result = FundingActivityReportingService.earnings_for_user(self.recipient.id)

        # Assert
        self.assertEqual(result["total_earned"], _ZERO_BREAKDOWN)
        self.assertEqual(result["by_source"], {})

    def test_earnings_for_user_with_no_activity(self):
        # Arrange
        empty_user = create_user(email="report-empty@test.com")

        # Act
        result = FundingActivityReportingService.earnings_for_user(empty_user.id)

        # Assert
        self.assertEqual(result["total_earned"], _ZERO_BREAKDOWN)
        self.assertEqual(result["by_source"], {})

    def test_earner_source_types_constant(self):
        # Arrange / Act / Assert
        self.assertNotIn(FundingActivity.FEE, EARNER_SOURCE_TYPES)
        self.assertIn(FundingActivity.USD_FUNDRAISE_PAYOUT, EARNER_SOURCE_TYPES)
