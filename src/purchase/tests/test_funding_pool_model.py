from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import FundingPool, Grant, Purchase
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user


class FundingPoolContributorsSummaryTests(TestCase):
    """FundingPool.get_contributors_summary ranks paid pool contributions by user."""

    def setUp(self):
        self.creator = create_random_authenticated_user("pool_model_creator")
        post = create_post(created_by=self.creator, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.creator,
            unified_document=post.unified_document,
            amount=1000,
            currency="USD",
            organization="Org",
            description="desc",
        )
        self.pool = FundingPool.objects.create(grant=grant, created_by=self.creator)
        self.pool_ct = ContentType.objects.get_for_model(FundingPool)

    def _contribute(self, user, amount):
        return Purchase.objects.create(
            user=user,
            content_type=self.pool_ct,
            object_id=self.pool.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDING_POOL_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=str(amount),
        )

    def test_sums_per_user_and_ranks_by_total(self):
        # Arrange
        small = create_random_authenticated_user("pool_small")
        big = create_random_authenticated_user("pool_big")
        self._contribute(small, 100)
        self._contribute(big, 60)
        self._contribute(big, 70)

        # Act
        summary = self.pool.get_contributors_summary()

        # Assert
        self.assertEqual(summary["total"], 2)
        self.assertEqual([c["user"] for c in summary["top"]], [big, small])
        self.assertEqual(summary["top"][0]["total_rsc"], Decimal(130))
        self.assertEqual(summary["top"][1]["total_rsc"], Decimal(100))
