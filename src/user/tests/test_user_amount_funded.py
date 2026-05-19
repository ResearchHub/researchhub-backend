"""Tests for User.amount_funded aligned with funder leaderboard data."""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from user.models import User
from user.related_models.funding_activity_model import FundingActivity
from user.serializers import DynamicAuthorProfileSerializer
from user.services.funding_activity_service import get_funder_total_amount
from user.tests.helpers import create_user


class UserAmountFundedTests(TestCase):
    def setUp(self):
        self.user = create_user(email="funder-amount@test.com")
        self.author = self.user.author_profile
        self.ct_user = ContentType.objects.get_for_model(User)
        self.now = timezone.now()

    def _create_activity(self, source_object_id, amount, source_type):
        return FundingActivity.objects.create(
            funder=self.user,
            source_type=source_type,
            total_amount=Decimal(str(amount)),
            activity_date=self.now,
            source_content_type=self.ct_user,
            source_object_id=source_object_id,
        )

    def test_user_amount_funded_matches_funding_activity_sum(self):
        self._create_activity(1, 200, FundingActivity.FUNDRAISE_PAYOUT)
        self._create_activity(2, 75, FundingActivity.BOUNTY_PAYOUT)
        self._create_activity(3, 25, FundingActivity.TIP_DOCUMENT)

        expected = get_funder_total_amount(self.user.id)
        self.assertEqual(expected, Decimal("300"))
        self.assertEqual(self.user.amount_funded, expected)

    def test_summary_stats_amount_funded_matches_leaderboard_aggregate(self):
        self._create_activity(10, 150, FundingActivity.FUNDRAISE_PAYOUT)
        self._create_activity(11, 50, FundingActivity.FEE)

        serializer = DynamicAuthorProfileSerializer(
            self.author,
            _include_fields=["summary_stats"],
        )
        self.assertEqual(
            serializer.data["summary_stats"]["amount_funded"],
            Decimal("200"),
        )
