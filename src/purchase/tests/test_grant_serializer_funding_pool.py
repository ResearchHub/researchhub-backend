from purchase.related_models.constants.currency import USD
from purchase.related_models.funding_pool_model import FundingPool
from purchase.related_models.grant_model import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.serializers import DynamicGrantSerializer
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import AWSMockTestCase


class GrantSerializerFundingPoolTests(AWSMockTestCase):
    """DynamicGrantSerializer exposes funding_pool holding/distributed/raised."""

    def setUp(self):
        super().setUp()
        RscExchangeRate.objects.create(
            rate=0.5,
            real_rate=0.5,
            target_currency="USD",
        )
        self.user = create_random_authenticated_user("grant_pool_ser")
        grant_post = create_post(created_by=self.user, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=1000,
            currency=USD,
            organization="Org",
            description="desc",
        )

    def test_funding_pool_none_when_missing(self):
        # Arrange / Act
        data = DynamicGrantSerializer(
            self.grant, _include_fields=["id", "funding_pool"]
        ).data

        # Assert
        self.assertIsNone(data["funding_pool"])

    def test_funding_pool_amounts_and_status(self):
        # Arrange
        pool = FundingPool.objects.create(
            grant=self.grant,
            created_by=self.user,
            amount_holding=100,
            amount_distributed=50,
            status=FundingPool.OPEN,
        )

        # Act
        data = DynamicGrantSerializer(
            self.grant, _include_fields=["id", "funding_pool"]
        ).data

        # Assert
        funding_pool = data["funding_pool"]
        self.assertEqual(funding_pool["id"], pool.id)
        self.assertEqual(funding_pool["status"], FundingPool.OPEN)
        self.assertEqual(float(funding_pool["amount_holding"]["rsc"]), 100.0)
        self.assertEqual(float(funding_pool["amount_distributed"]["rsc"]), 50.0)
        self.assertEqual(float(funding_pool["amount_raised"]["rsc"]), 150.0)
        self.assertIn("usd", funding_pool["amount_holding"])
        self.assertIn("usd", funding_pool["amount_distributed"])
        self.assertIn("usd", funding_pool["amount_raised"])
        self.assertNotIn("created_by", funding_pool)
        self.assertNotIn("grant", funding_pool)
