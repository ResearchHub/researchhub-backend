from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from purchase.models import Balance, FundingPool, Grant, Purchase, RscExchangeRate
from purchase.services.funding_pool_service import FundingPoolService
from reputation.models import BountyFee
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC,
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
