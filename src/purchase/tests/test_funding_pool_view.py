from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

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
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.follow_model import Follow
from user.tests.helpers import create_random_authenticated_user, create_user


class FundingPoolViewTests(APITestCase):
    def setUp(self):
        self.creator = create_random_authenticated_user("pool_view_creator")
        self.post = create_post(created_by=self.creator, document_type=GRANT_DOC)
        self.grant = Grant.objects.create(
            created_by=self.creator,
            unified_document=self.post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="Test Org",
            description="Test grant",
        )
        self.pool = FundingPoolService().create_pool_for_grant(self.grant)

        RscExchangeRate.objects.create(
            rate=0.5,
            real_rate=0.5,
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        create_user(email="bank@researchhub.com")
        BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

    def _give_user_balance(self, user, amount):
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

    def _create_contribution(self, pool_id, user, amount=100, use_credits=None):
        self.client.force_authenticate(user)
        payload = {"amount": amount, "amount_currency": "RSC"}
        if use_credits is not None:
            payload["use_credits"] = use_credits
        return self.client.post(
            f"/api/funding_pool/{pool_id}/create_contribution/",
            payload,
        )

    def _seed_pool_holding(self, amount=Decimal(200)):
        contributor = create_random_authenticated_user("pool_view_seed")
        self._give_user_balance(contributor, 1000)
        response = self._create_contribution(
            self.pool.id, contributor, amount=amount, use_credits=False
        )
        self.assertEqual(response.status_code, 200)
        self.pool.refresh_from_db()

    def _create_proposal_application_with_fundraise(self, grant=None):
        grant = grant or self.grant
        applicant = create_random_authenticated_user("pool_view_applicant")
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

    def test_retrieve_funding_pool(self):
        # Arrange
        self.client.force_authenticate(self.creator)

        # Act
        response = self.client.get(f"/api/funding_pool/{self.pool.id}/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.pool.id)
        self.assertEqual(response.data["status"], FundingPool.OPEN)
        self.assertEqual(float(response.data["amount_holding"]["rsc"]), 0.0)

    def test_create_contribution(self):
        # Arrange
        user = create_random_authenticated_user("pool_view_contributor")
        self._give_user_balance(user, 1000)

        # Act
        response = self._create_contribution(self.pool.id, user, use_credits=False)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(float(response.data["amount_holding"]["rsc"]), 100.0)
        self.assertEqual(float(response.data["amount_raised"]["rsc"]), 100.0)

        amount_balance = Balance.objects.filter(
            user=user, content_type=ContentType.objects.get_for_model(Purchase)
        )
        self.assertEqual(amount_balance.count(), 1)
        self.assertEqual(float(amount_balance.first().amount), -100.0)

        fee_balance = Balance.objects.filter(
            user=user, content_type=ContentType.objects.get_for_model(BountyFee)
        )
        self.assertEqual(fee_balance.count(), 1)
        self.assertEqual(float(fee_balance.first().amount), -9.0)

        follow = Follow.objects.filter(
            user=user,
            object_id=self.post.id,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
        )
        self.assertEqual(follow.count(), 1)

    def test_create_contribution_with_funding_credits(self):
        # Arrange
        user = create_random_authenticated_user("pool_credits_view")
        self._give_funding_credits(user, 200)

        # Act
        response = self._create_contribution(self.pool.id, user, use_credits=True)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(float(response.data["amount_holding"]["rsc"]), 100.0)

    def test_create_contribution_not_enough_funds(self):
        # Arrange
        user = create_random_authenticated_user("pool_broke_view")
        self._give_user_balance(user, 10)

        # Act
        response = self._create_contribution(
            self.pool.id, user, amount=100, use_credits=False
        )

        # Assert
        self.assertEqual(response.status_code, 400)

    def test_create_contribution_rejects_usd(self):
        # Arrange
        user = create_random_authenticated_user("pool_usd_view")
        self.client.force_authenticate(user)

        # Act
        response = self.client.post(
            f"/api/funding_pool/{self.pool.id}/create_contribution/",
            {"amount": 100, "amount_currency": "USD"},
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("amount_currency", response.data)

    def test_distribute_as_grant_creator(self):
        # Arrange
        self._seed_pool_holding(Decimal(200))
        _, application, fundraise = self._create_proposal_application_with_fundraise()
        creator_balance_before = self.creator.get_available_balance()
        self.client.force_authenticate(self.creator)

        # Act
        response = self.client.post(
            f"/api/funding_pool/{self.pool.id}/distribute/",
            {"amount": 75, "application_id": application.id},
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(float(response.data["amount_holding"]["rsc"]), 125.0)
        self.assertEqual(float(response.data["amount_distributed"]["rsc"]), 75.0)
        self.assertEqual(float(response.data["amount_raised"]["rsc"]), 200.0)

        fundraise.escrow.refresh_from_db()
        self.assertEqual(fundraise.escrow.amount_holding, Decimal(75))
        self.assertEqual(self.creator.get_available_balance(), creator_balance_before)

        distribution = FundingDistribution.objects.get(pool=self.pool)
        self.assertEqual(distribution.status, FundingDistribution.APPLIED)
        self.assertEqual(distribution.amount, Decimal(75))
        self.assertEqual(
            Balance.objects.filter(purchase=distribution.fundraise_purchase).count(),
            0,
        )

    def test_distribute_as_moderator(self):
        # Arrange
        self._seed_pool_holding(Decimal(100))
        _, application, _ = self._create_proposal_application_with_fundraise()
        moderator = create_random_authenticated_user(
            "pool_view_moderator", moderator=True
        )
        self.client.force_authenticate(moderator)

        # Act
        response = self.client.post(
            f"/api/funding_pool/{self.pool.id}/distribute/",
            {"amount": 40, "application_id": application.id},
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(float(response.data["amount_holding"]["rsc"]), 60.0)
        self.assertEqual(float(response.data["amount_distributed"]["rsc"]), 40.0)

        distribution = FundingDistribution.objects.get(pool=self.pool)
        self.assertEqual(distribution.distributed_by_id, moderator.id)

    def test_distribute_permission_denied_for_non_creator(self):
        # Arrange
        self._seed_pool_holding(Decimal(100))
        _, application, _ = self._create_proposal_application_with_fundraise()
        outsider = create_random_authenticated_user("pool_view_outsider")
        self.client.force_authenticate(outsider)

        # Act
        response = self.client.post(
            f"/api/funding_pool/{self.pool.id}/distribute/",
            {"amount": 25, "application_id": application.id},
        )

        # Assert
        self.assertEqual(response.status_code, 403)
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.amount_holding, Decimal(100))
        self.assertEqual(self.pool.amount_distributed, Decimal(0))

    def test_distribute_overspend_blocked(self):
        # Arrange
        self._seed_pool_holding(Decimal(50))
        _, application, _ = self._create_proposal_application_with_fundraise()
        self.client.force_authenticate(self.creator)

        # Act
        response = self.client.post(
            f"/api/funding_pool/{self.pool.id}/distribute/",
            {"amount": 51, "application_id": application.id},
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient pool balance", response.data["message"])
        self.pool.refresh_from_db()
        self.assertEqual(self.pool.amount_holding, Decimal(50))

    def test_distribute_rejects_application_from_other_grant(self):
        # Arrange
        self._seed_pool_holding(Decimal(100))
        other_creator = create_random_authenticated_user("other_grant_view")
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
        self.client.force_authenticate(self.creator)

        # Act
        response = self.client.post(
            f"/api/funding_pool/{self.pool.id}/distribute/",
            {"amount": 25, "application_id": other_application.id},
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("does not belong", response.data["message"])

    def test_distribute_rejects_closed_fundraise(self):
        # Arrange
        self._seed_pool_holding(Decimal(100))
        _, application, fundraise = self._create_proposal_application_with_fundraise()
        fundraise.status = Fundraise.CLOSED
        fundraise.save(update_fields=["status"])
        self.client.force_authenticate(self.creator)

        # Act
        response = self.client.post(
            f"/api/funding_pool/{self.pool.id}/distribute/",
            {"amount": 25, "application_id": application.id},
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("not open", response.data["message"])

    def test_grant_create_via_api_creates_funding_pool(self):
        # Arrange
        user = create_random_authenticated_user("grant_pool_api")
        self.client.force_authenticate(user)
        new_post = create_post(created_by=user, document_type=GRANT_DOC)

        # Act
        response = self.client.post(
            "/api/grant/",
            {
                "unified_document_id": new_post.unified_document.id,
                "amount": "25000.00",
                "currency": "USD",
                "organization": "Pool Foundation",
                "description": "Grant that should create a pool",
            },
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        grant = Grant.objects.get(id=response.data["id"])
        self.assertTrue(hasattr(grant, "funding_pool"))
        self.assertEqual(grant.funding_pool.created_by_id, user.id)
        self.assertEqual(grant.funding_pool.status, FundingPool.OPEN)
