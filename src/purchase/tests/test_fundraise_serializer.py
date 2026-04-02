from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Fundraise
from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.serializers.fundraise_serializer import DynamicFundraiseSerializer
from purchase.services.fundraise_service import FundraiseService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user


class GetContributorsTests(TestCase):
    """
    Tests for DynamicFundraiseSerializer's `get_contributors` method.
    """

    def setUp(self):
        self.user = create_random_authenticated_user("fundraise_owner", moderator=True)
        self.contributor1 = create_random_authenticated_user("contributor1")
        self.contributor2 = create_random_authenticated_user("contributor2")

        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        self.fundraise_service = FundraiseService()
        self.fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=1000,
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        self.fundraise_ct = ContentType.objects.get_for_model(Fundraise)

        RscExchangeRate.objects.create(
            rate=0.01,
            real_rate=0.01,
            price_source="COIN_GECKO",
            target_currency="USD",
        )

    def _create_rsc_contribution(self, user, amount, rsc_usd_rate):
        return Purchase.objects.create(
            user=user,
            content_type=self.fundraise_ct,
            object_id=self.fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            amount=str(amount),
            paid_status="PAID",
            rsc_usd_rate=rsc_usd_rate,
        )

    def _create_usd_contribution(self, user, amount_cents):
        return UsdFundraiseContribution.objects.create(
            user=user,
            fundraise=self.fundraise,
            amount_cents=amount_cents,
            fee_cents=int(amount_cents * 0.09),
        )

    def _serialize(self):
        serializer = DynamicFundraiseSerializer(
            self.fundraise,
            context={
                "pch_dfs_get_contributors": {
                    "_include_fields": ["id", "first_name", "last_name"],
                },
            },
            _include_fields=["contributors"],
        )
        return serializer.data["contributors"]

    def test_no_contributions(self):
        # Act
        result = self._serialize()

        # Assert
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["top"], [])

    def test_rsc_contributions_only(self):
        # Arrange
        self._create_rsc_contribution(self.contributor1, 100, rsc_usd_rate=0.05)
        self._create_rsc_contribution(self.contributor1, 50, rsc_usd_rate=0.10)

        # Act
        result = self._serialize()

        # Assert
        self.assertEqual(result["total"], 1)
        top = result["top"]
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["total_contribution"]["rsc"], 150.0)
        self.assertEqual(top[0]["total_contribution"]["usd"], 0)
        # 100 * 0.05 + 50 * 0.10 = 5.0 + 5.0 = 10.0
        self.assertAlmostEqual(top[0]["total_contribution"]["rsc_usd_snapshot"], 10.0)
        self.assertEqual(len(top[0]["contributions"]), 2)

    def test_usd_contributions_only(self):
        # Arrange
        self._create_usd_contribution(self.contributor1, 10000)  # $100

        # Act
        result = self._serialize()

        # Assert
        self.assertEqual(result["total"], 1)
        top = result["top"]
        self.assertEqual(top[0]["total_contribution"]["usd"], 100.0)
        self.assertEqual(top[0]["total_contribution"]["rsc"], 0)
        self.assertEqual(top[0]["total_contribution"]["rsc_usd_snapshot"], 0)

    def test_mixed_rsc_and_usd_from_same_user(self):
        # Arrange
        self._create_rsc_contribution(self.contributor1, 200, rsc_usd_rate=0.01)
        self._create_usd_contribution(self.contributor1, 5000)  # $50

        # Act
        result = self._serialize()

        # Assert
        self.assertEqual(result["total"], 1)
        top = result["top"]
        self.assertEqual(top[0]["total_contribution"]["rsc"], 200.0)
        self.assertEqual(top[0]["total_contribution"]["usd"], 50.0)
        # 200 * 0.01 = 2.0
        self.assertAlmostEqual(top[0]["total_contribution"]["rsc_usd_snapshot"], 2.0)
        self.assertEqual(len(top[0]["contributions"]), 2)

    @patch(
        "purchase.serializers.fundraise_serializer.RscExchangeRate.rsc_to_usd",
        side_effect=lambda rsc: rsc * 0.01,
    )
    def test_multiple_users_sorted_by_usd_equivalent(self, _mock):
        # Arrange
        # contributor1: 100 RSC ($1) + $0 USD = $1 equivalent
        self._create_rsc_contribution(self.contributor1, 100, rsc_usd_rate=0.01)
        # contributor2: $50 USD + 0 RSC = $50 equivalent
        self._create_usd_contribution(self.contributor2, 5000)

        # Act
        result = self._serialize()

        # Assert
        self.assertEqual(result["total"], 2)
        top = result["top"]
        # contributor2 ($50) should be first
        self.assertEqual(top[0]["id"], self.contributor2.id)
        self.assertEqual(top[1]["id"], self.contributor1.id)

    def test_excludes_refunded_usd_contributions(self):
        # Arrange
        self._create_usd_contribution(self.contributor1, 10000)  # $100
        refunded = self._create_usd_contribution(self.contributor2, 5000)  # $50
        refunded.is_refunded = True
        refunded.save()

        # Act
        result = self._serialize()

        # Assert
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["top"][0]["id"], self.contributor1.id)

    def test_contributions_sorted_by_date_descending(self):
        # Arrange
        self._create_rsc_contribution(self.contributor1, 100, rsc_usd_rate=0.01)
        self._create_rsc_contribution(self.contributor1, 200, rsc_usd_rate=0.01)

        # Act
        result = self._serialize()

        # Assert
        contributions = result["top"][0]["contributions"]
        self.assertEqual(len(contributions), 2)
        self.assertTrue(contributions[0]["date"] >= contributions[1]["date"])

    def test_contribution_currency_labels(self):
        # Arrange
        self._create_rsc_contribution(self.contributor1, 100, rsc_usd_rate=0.01)
        self._create_usd_contribution(self.contributor1, 5000)

        # Act
        result = self._serialize()

        # Assert
        contributions = result["top"][0]["contributions"]
        currencies = {c["currency"] for c in contributions}
        self.assertEqual(currencies, {RSC, USD})
