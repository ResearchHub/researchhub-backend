from rest_framework.test import APITestCase
from django.contrib.contenttypes.models import ContentType

from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import (
    create_random_authenticated_user,
    create_user
)
from purchase.models import Balance, RscExchangeRate, Purchase
from reputation.models import Escrow, BountyFee


class FundraiseViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("fundraise_views", moderator=True)
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        self.rsc_exchange_rate = RscExchangeRate.objects.create(
            rate=0.5,
            real_rate=0.5,
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        self.bank_user = create_user(email="bank@researchhub.com")
        self.bounty_fee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

    # Helpers

    def _create_fundraise(
            self,
            post_id,
            goal_amount = 100,
            goal_currency = "USD",
            user = None
            ):
        if user is None:
            user = self.user

        self.client.force_authenticate(user)
        return self.client.post(
            "/api/fundraise/",
            {
                "post_id": post_id,
                "recipient_user_id": user.id,
                "goal_amount": goal_amount,
                "goal_currency": goal_currency,
            },
        )

    def _create_contribution(
            self,
            fundraise_id,
            user,
            amount = 100,
            amount_currency = "RSC",
            ):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/api/fundraise/{fundraise_id}/create_contribution/",
            {
                "amount": amount,
                "amount_currency": amount_currency,
            },
        )
    
    def _get_contributions(self, fundraise_id):
        return self.client.get(f"/api/fundraise/{fundraise_id}/contributions/")
    
    def _give_user_balance(self, user, amount):
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount=amount, user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )


    # Fundraise tests

    def test_create_fundraise(self):
        response = self._create_fundraise(self.post.id)

        self.assertIsNotNone(response.data["id"])

        # check fundraise
        self.assertEqual(response.data["goal_amount"]["usd"], 100)
        self.assertEqual(response.data["goal_currency"], "USD")
        self.assertEqual(response.data["amount_raised"]["usd"], 0)
        # check created_by
        self.assertEqual(response.data["created_by"]["id"], self.user.id)
        # check escrow
        self.assertEqual(response.data["escrow"]["hold_type"], "FUNDRAISE")
        self.assertEqual(float(response.data["escrow"]["amount_holding"]), 0.0)

    def test_create_fundraise_no_post(self):
        response = self._create_fundraise(9999)
        self.assertEqual(response.status_code, 400)

    def test_create_fundraise_not_preregistration(self):
        self.client.force_authenticate(self.user)
        post = create_post(created_by=self.user, document_type="DISCUSSION")
        response = self._create_fundraise(post.id)

        self.assertEqual(response.status_code, 400)

    def test_create_fundraise_already_exists(self):
        response = self._create_fundraise(self.post.id)

        self.assertIsNotNone(response.data["id"])

        response = self._create_fundraise(self.post.id)

        self.assertEqual(response.status_code, 400)

    def test_create_fundraise_not_moderator(self):
        user = create_random_authenticated_user("fundraise_views")
        self.client.force_authenticate(user)
        response = self._create_fundraise(self.post.id, user=user)

        self.assertEqual(response.status_code, 403)

    # Contribution tests

    def test_create_contribution(self):
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(fundraise_id, user)

        self.assertEqual(response.status_code, 200)

        updated_fundraise = response.data
        self.assertEqual(updated_fundraise["amount_raised"]["rsc"], 100)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_holding"]), 100.0)

        # there should be two balance objects for the user, one for the '100', and one for fees
        amount_balance = Balance.objects.filter(user=user, content_type=ContentType.objects.get_for_model(Purchase))
        self.assertEqual(amount_balance.count(), 1)
        self.assertEqual(float(amount_balance.first().amount), -100.0)
        fee_balance = Balance.objects.filter(user=user, content_type=ContentType.objects.get_for_model(BountyFee))
        self.assertEqual(fee_balance.count(), 1)
        self.assertEqual(float(fee_balance.first().amount), -9.0)

    def test_create_contribution_already_contributed(self):
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(fundraise_id, user, amount=50)
        response = self._create_contribution(fundraise_id, user, amount=50)

        self.assertEqual(response.status_code, 200)

        updated_fundraise = response.data
        self.assertEqual(updated_fundraise["amount_raised"]["rsc"], 100)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_holding"]), 100.0)

        # there should be 2 balance objects for amount, and 2 for fees
        amount_balance = Balance.objects.filter(user=user, content_type=ContentType.objects.get_for_model(Purchase))
        self.assertEqual(amount_balance.count(), 2)
        fee_balance = Balance.objects.filter(user=user, content_type=ContentType.objects.get_for_model(BountyFee))
        self.assertEqual(fee_balance.count(), 2)

        # fetch contributions and check them
        contributions = self._get_contributions(fundraise_id)
        self.assertEqual(len(contributions.data), 2)
        self.assertEqual(contributions.data[0]["user"]["id"], user.id)
        self.assertEqual(float(contributions.data[0]["amount"]), 50.0)
        self.assertEqual(contributions.data[1]["user"]["id"], user.id)
        self.assertEqual(float(contributions.data[1]["amount"]), 50.0)

    def test_create_contribution_not_enough_funds(self):
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 10)
        response = self._create_contribution(fundraise_id, user, amount=100)

        self.assertEqual(response.status_code, 400)

    def test_create_contribution_user_is_owner(self):
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        response = self._create_contribution(fundraise_id, self.user)

        self.assertEqual(response.status_code, 400)

    def test_create_contribution_fulfills_goal(self):
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(fundraise_id, user, amount=200) # 200 RSC = 100 USD

        self.assertEqual(response.status_code, 200)

        updated_fundraise = response.data
        self.assertEqual(updated_fundraise["amount_raised"]["rsc"], 200)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_holding"]), 0.0)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_paid"]), 200.0)
        self.assertEqual(updated_fundraise["status"], "CLOSED")

        # there should be two balance objects for the user, one for the '100', and one for fees
        amount_balance = Balance.objects.filter(user=user, content_type=ContentType.objects.get_for_model(Purchase))
        self.assertEqual(amount_balance.count(), 1)
        self.assertEqual(float(amount_balance.first().amount), -200.0)
        fee_balance = Balance.objects.filter(user=user, content_type=ContentType.objects.get_for_model(BountyFee))
        self.assertEqual(fee_balance.count(), 1)
        self.assertEqual(float(fee_balance.first().amount), -18.0)

        # check that the owner was paid out
        owner_balance = Balance.objects.filter(user=self.user)
        self.assertEqual(owner_balance.count(), 1)
        self.assertEqual(float(owner_balance.first().amount), 200.0)
