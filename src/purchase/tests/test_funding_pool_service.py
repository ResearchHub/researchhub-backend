from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Balance, FundingPool, Grant, Purchase, RscExchangeRate
from purchase.services.funding_pool_service import FundingPoolService
from reputation.models import BountyFee
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC,
)
from user.tests.helpers import create_random_authenticated_user, create_user


class FundingPoolServiceTests(TestCase):
    def setUp(self):
        self.creator = create_random_authenticated_user("pool_creator")
        self.post = create_post(created_by=self.creator, document_type=GRANT_DOC)
        self.grant = Grant.objects.create(
            created_by=self.creator,
            unified_document=self.post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="Test Org",
            description="Test grant",
        )
        self.service = FundingPoolService()
        self.pool = self.service.create_pool_for_grant(self.grant)

        self.bounty_fee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)
        RscExchangeRate.objects.create(
            rate=0.5,
            real_rate=0.5,
            target_currency="USD",
        )
        create_user(email="bank@researchhub.com")

    def _give_available_balance(self, user, amount):
        distribution_ct = ContentType.objects.get(model="distribution")
        Balance.objects.create(amount=amount, user=user, content_type=distribution_ct)

    def _give_funding_credits(self, user, amount):
        distribution_ct = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount=amount,
            user=user,
            content_type=distribution_ct,
            is_locked=True,
            lock_type=Balance.LockType.FUNDING_CREDIT,
        )

    def test_create_pool_for_grant_is_idempotent(self):
        # Act
        again = self.service.create_pool_for_grant(self.grant)

        # Assert
        self.assertEqual(again.id, self.pool.id)
        self.assertEqual(FundingPool.objects.filter(grant=self.grant).count(), 1)

    def test_create_rsc_contribution_with_available_balance(self):
        # Arrange
        contributor = create_random_authenticated_user("pool_contributor")
        self._give_available_balance(contributor, 1000)

        # Act
        purchase, error = self.service.create_rsc_contribution(
            contributor, self.pool, Decimal(100), use_credits=False
        )

        # Assert
        self.assertIsNone(error)
        self.assertIsNotNone(purchase)
        self.assertEqual(purchase.purchase_type, Purchase.FUNDING_POOL_CONTRIBUTION)
        self.assertEqual(purchase.object_id, self.pool.id)

        self.pool.refresh_from_db()
        self.assertEqual(self.pool.amount_holding, Decimal(100))
        self.assertEqual(self.pool.amount_raised, Decimal(100))

        amount_balance = Balance.objects.filter(
            user=contributor, content_type=ContentType.objects.get_for_model(Purchase)
        )
        self.assertEqual(amount_balance.count(), 1)
        self.assertEqual(float(amount_balance.first().amount), -100.0)

        fee_balance = Balance.objects.filter(
            user=contributor, content_type=ContentType.objects.get_for_model(BountyFee)
        )
        self.assertEqual(fee_balance.count(), 1)
        self.assertEqual(float(fee_balance.first().amount), -9.0)

    def test_create_rsc_contribution_with_funding_credits(self):
        # Arrange
        contributor = create_random_authenticated_user("credits_pool_contributor")
        self._give_funding_credits(contributor, 200)
        self._give_available_balance(contributor, 500)

        # Act
        purchase, error = self.service.create_rsc_contribution(
            contributor, self.pool, Decimal(100), use_credits=True
        )

        # Assert
        self.assertIsNone(error)
        debits = Balance.objects.filter(purchase=purchase)
        self.assertTrue(
            all(
                debit.is_locked and debit.lock_type == Balance.LockType.FUNDING_CREDIT
                for debit in debits
            )
        )
        self.assertEqual(contributor.get_available_balance(), Decimal(500))

    def test_create_rsc_contribution_insufficient_credits(self):
        # Arrange
        contributor = create_random_authenticated_user("short_credits_pool")
        self._give_funding_credits(contributor, 50)
        self._give_available_balance(contributor, 1000)

        # Act
        purchase, error = self.service.create_rsc_contribution(
            contributor, self.pool, Decimal(100), use_credits=True
        )

        # Assert
        self.assertIsNone(purchase)
        self.assertEqual(error, "Insufficient funding credit balance")
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.amount_holding, Decimal(0))

    def test_create_contribution_rejects_closed_pool(self):
        # Arrange
        self.pool.status = FundingPool.CLOSED
        self.pool.save()
        contributor = create_random_authenticated_user("closed_pool_contributor")
        self._give_available_balance(contributor, 1000)

        # Act
        purchase, error = self.service.create_contribution(
            contributor, self.pool, Decimal(100), use_credits=False
        )

        # Assert
        self.assertIsNone(purchase)
        self.assertEqual(error, "Funding pool is not open")

    def test_create_contribution_rejects_usd(self):
        # Arrange
        contributor = create_random_authenticated_user("usd_pool_contributor")

        # Act
        purchase, error = self.service.create_contribution(
            contributor, self.pool, Decimal(100), currency="USD"
        )

        # Assert
        self.assertIsNone(purchase)
        self.assertIn("Only RSC", error)
