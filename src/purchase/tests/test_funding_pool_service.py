from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import (
    Balance,
    FundingDistribution,
    FundingPool,
    Fundraise,
    Grant,
    GrantApplication,
    Purchase,
    RscExchangeRate,
)
from purchase.services.funding_pool_service import FundingPoolService
from purchase.services.fundraise_service import FundraiseService
from reputation.models import BountyFee
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC,
)
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
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

    def _seed_pool_holding(self, amount=Decimal(200)):
        contributor = create_random_authenticated_user("pool_seed_contributor")
        self._give_available_balance(contributor, 1000)
        purchase, error = self.service.create_rsc_contribution(
            contributor, self.pool, amount, use_credits=False
        )
        self.assertIsNone(error)
        self.pool.refresh_from_db()
        return purchase

    def _create_proposal_application_with_fundraise(self, grant=None):
        grant = grant or self.grant
        applicant = create_random_authenticated_user("pool_applicant")
        proposal = create_post(created_by=applicant, document_type=PREREGISTRATION)
        application = GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal,
            applicant=applicant,
        )
        fundraise = FundraiseService().create_fundraise_with_escrow(
            user=applicant,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
        )
        return applicant, application, fundraise

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

    def test_distribute_to_open_proposal_fundraise(self):
        # Arrange
        self._seed_pool_holding(Decimal(200))
        _, application, fundraise = self._create_proposal_application_with_fundraise()
        creator_balance_before = self.creator.get_available_balance()

        # Act
        distribution, error = self.service.distribute(
            self.pool,
            self.creator,
            Decimal(75),
            application.id,
        )

        # Assert
        self.assertIsNone(error)
        self.assertIsNotNone(distribution)
        self.assertEqual(distribution.status, FundingDistribution.APPLIED)
        self.assertEqual(distribution.amount, Decimal(75))
        self.assertEqual(distribution.application_id, application.id)
        self.assertEqual(distribution.target_fundraise_id, fundraise.id)

        self.pool.refresh_from_db()
        self.assertEqual(self.pool.amount_holding, Decimal(125))
        self.assertEqual(self.pool.amount_distributed, Decimal(75))
        self.assertEqual(self.pool.amount_raised, Decimal(200))

        fundraise.escrow.refresh_from_db()
        self.assertEqual(fundraise.escrow.amount_holding, Decimal(75))

        purchase = distribution.fundraise_purchase
        self.assertEqual(purchase.purchase_type, Purchase.FUNDRAISE_CONTRIBUTION)
        self.assertEqual(purchase.user_id, self.creator.id)
        self.assertEqual(purchase.object_id, fundraise.id)
        self.assertEqual(Balance.objects.filter(purchase=purchase).count(), 0)
        self.assertEqual(self.creator.get_available_balance(), creator_balance_before)

    def test_distribute_overspend_blocked(self):
        # Arrange
        self._seed_pool_holding(Decimal(50))
        _, application, _ = self._create_proposal_application_with_fundraise()

        # Act
        distribution, error = self.service.distribute(
            self.pool,
            self.creator,
            Decimal(51),
            application.id,
        )

        # Assert
        self.assertIsNone(distribution)
        self.assertEqual(error, "Insufficient pool balance")
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.amount_holding, Decimal(50))
        self.assertEqual(self.pool.amount_distributed, Decimal(0))

    def test_distribute_rejects_application_from_other_grant(self):
        # Arrange
        self._seed_pool_holding(Decimal(100))
        other_creator = create_random_authenticated_user("other_grant_creator")
        other_post = create_post(created_by=other_creator, document_type=GRANT_DOC)
        other_grant = Grant.objects.create(
            created_by=other_creator,
            unified_document=other_post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            organization="Other Org",
            description="Other grant",
        )
        _, other_application, _ = self._create_proposal_application_with_fundraise(
            grant=other_grant
        )

        # Act
        distribution, error = self.service.distribute(
            self.pool,
            self.creator,
            Decimal(25),
            other_application.id,
        )

        # Assert
        self.assertIsNone(distribution)
        self.assertEqual(error, "Application does not belong to this grant")

    def test_distribute_rejects_closed_fundraise(self):
        # Arrange
        self._seed_pool_holding(Decimal(100))
        _, application, fundraise = self._create_proposal_application_with_fundraise()
        fundraise.status = Fundraise.CLOSED
        fundraise.save(update_fields=["status"])

        # Act
        distribution, error = self.service.distribute(
            self.pool,
            self.creator,
            Decimal(25),
            application.id,
        )

        # Assert
        self.assertIsNone(distribution)
        self.assertEqual(error, "Fundraise is not open")

    def test_distribute_rejects_closed_pool(self):
        # Arrange
        self._seed_pool_holding(Decimal(100))
        _, application, _ = self._create_proposal_application_with_fundraise()
        self.pool.status = FundingPool.CLOSED
        self.pool.save(update_fields=["status"])

        # Act
        distribution, error = self.service.distribute(
            self.pool,
            self.creator,
            Decimal(25),
            application.id,
        )

        # Assert
        self.assertIsNone(distribution)
        self.assertEqual(error, "Funding pool is not open")
