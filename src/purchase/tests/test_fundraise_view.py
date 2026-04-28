from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytz
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.models import (
    Balance,
    Fundraise,
    Purchase,
    RscExchangeRate,
    UsdFundraiseContribution,
)
from purchase.services.fundraise_service import (
    USD_CONTRIBUTION_CSV_HEADERS,
    FundraiseService,
)
from purchase.views import FundraiseViewSet
from referral.models import ReferralSignup
from referral.services.referral_bonus_service import ReferralBonusService
from reputation.models import BountyFee, Distribution
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.follow_model import Follow
from user.tests.helpers import create_random_authenticated_user, create_user


class FundraiseViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("fundraise_views", moderator=True)
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        self.factory = APIRequestFactory()
        self.mock_fundraise_service = Mock(spec=FundraiseService)

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
        self, post_id, goal_amount=100, goal_currency="USD", user=None
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
        amount=100,
        amount_currency="RSC",
        origin_fund_id=None,
        use_credits=None,
    ):
        self.client.force_authenticate(user)
        payload = {
            "amount": amount,
            "amount_currency": amount_currency,
        }
        if origin_fund_id:
            payload["origin_fund_id"] = origin_fund_id
        if use_credits is not None:
            payload["use_credits"] = use_credits
        return self.client.post(
            f"/api/fundraise/{fundraise_id}/create_contribution/",
            payload,
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
        response = self._create_contribution(fundraise_id, user, use_credits=False)

        self.assertEqual(response.status_code, 200)

        updated_fundraise = response.data
        self.assertEqual(updated_fundraise["amount_raised"]["rsc"], 100)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_holding"]), 100.0)

        # there should be two balance objects for the user, one for the '100', and one for fees
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

        # check that the user is following the preregistration
        follow = Follow.objects.filter(
            user=user,
            object_id=self.post.id,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
        )
        self.assertEqual(follow.count(), 1)

    def test_create_contribution_already_contributed(self):
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(
            fundraise_id, user, amount=50, use_credits=False
        )
        response = self._create_contribution(
            fundraise_id, user, amount=50, use_credits=False
        )

        self.assertEqual(response.status_code, 200)

        updated_fundraise = response.data
        self.assertEqual(updated_fundraise["amount_raised"]["rsc"], 100)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_holding"]), 100.0)

        # there should be 2 balance objects for amount, and 2 for fees
        amount_balance = Balance.objects.filter(
            user=user, content_type=ContentType.objects.get_for_model(Purchase)
        )
        self.assertEqual(amount_balance.count(), 2)
        fee_balance = Balance.objects.filter(
            user=user, content_type=ContentType.objects.get_for_model(BountyFee)
        )
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
        """Self-contribution without a nonprofit should be rejected."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        self._give_user_balance(self.user, 1000)
        response = self._create_contribution(fundraise_id, self.user)

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Cannot contribute to your own fundraise", response.data["message"]
        )

    def test_create_contribution_user_is_owner_with_nonprofit(self):
        """Self-contribution should be allowed when a nonprofit is attached."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]
        self._link_nonprofit(fundraise_id)

        self._give_user_balance(self.user, 1000)
        response = self._create_contribution(
            fundraise_id, self.user, amount=100, use_credits=False
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["amount_raised"]["rsc"], 100)

    def test_create_contribution_exceeds_goal(self):
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(
            fundraise_id, user, amount=200, use_credits=False
        )  # 200 RSC = 100 USD

        self.assertEqual(response.status_code, 200)

        updated_fundraise = response.data
        self.assertEqual(updated_fundraise["amount_raised"]["rsc"], 200)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_holding"]), 200.0)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_paid"]), 0.0)
        self.assertEqual(
            updated_fundraise["status"], "OPEN"
        )  # Should remain open until manually completed

        # there should be two balance objects for the user, one for the contribution and one for fees
        amount_balance = Balance.objects.filter(
            user=user, content_type=ContentType.objects.get_for_model(Purchase)
        )
        self.assertEqual(amount_balance.count(), 1)
        self.assertEqual(float(amount_balance.first().amount), -200.0)
        fee_balance = Balance.objects.filter(
            user=user, content_type=ContentType.objects.get_for_model(BountyFee)
        )
        self.assertEqual(fee_balance.count(), 1)
        self.assertEqual(float(fee_balance.first().amount), -18.0)

        # check that the owner has NOT been paid out yet (no automatic payout)
        owner_balance = Balance.objects.filter(user=self.user)
        self.assertEqual(owner_balance.count(), 0)

    def test_create_contribution_expired_fundraise(self):
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        # update fundraise end_date to 1 day ago
        fundraise = Fundraise.objects.get(id=fundraise_id)
        fundraise.end_date = datetime.now(pytz.UTC) - timedelta(days=1)
        fundraise.save()

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(fundraise_id, user, amount=200)

        self.assertEqual(response.status_code, 400)

    def test_fundraise_contributors_data_structure(self):
        # Create a fundraise
        fundraise_response = self._create_fundraise(self.post.id, goal_amount=500)
        fundraise_id = fundraise_response.data["id"]

        # Create multiple users who will contribute
        user1 = create_random_authenticated_user("fundraise_contributor1")
        user2 = create_random_authenticated_user("fundraise_contributor2")
        user3 = create_random_authenticated_user("fundraise_contributor3")

        # Give users balance
        self._give_user_balance(user1, 1000)
        self._give_user_balance(user2, 1000)
        self._give_user_balance(user3, 1000)

        # Have users make multiple contributions of different amounts
        self._create_contribution(fundraise_id, user1, amount=100, use_credits=False)
        self._create_contribution(fundraise_id, user1, amount=50, use_credits=False)
        self._create_contribution(fundraise_id, user2, amount=200, use_credits=False)
        self._create_contribution(fundraise_id, user3, amount=75, use_credits=False)

        # Get the fundraise data
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/fundraise/{fundraise_id}/")

        # Check contributors structure
        contributors = response.data["contributors"]

        # Verify total count
        self.assertEqual(contributors["total"], 3)

        # Verify contributors are sorted by total contribution (descending)
        top_contributors = contributors["top"]
        self.assertEqual(len(top_contributors), 3)

        # User2 should be first (200 RSC)
        self.assertEqual(top_contributors[0]["id"], user2.id)
        self.assertEqual(top_contributors[0]["total_contribution"]["rsc"], 200.0)
        self.assertEqual(top_contributors[0]["total_contribution"]["usd"], 0)
        self.assertEqual(len(top_contributors[0]["contributions"]), 1)

        # User1 should be second (150 RSC total)
        self.assertEqual(top_contributors[1]["id"], user1.id)
        self.assertEqual(top_contributors[1]["total_contribution"]["rsc"], 150.0)
        self.assertEqual(top_contributors[1]["total_contribution"]["usd"], 0)
        self.assertEqual(len(top_contributors[1]["contributions"]), 2)

        # User3 should be third (75 RSC)
        self.assertEqual(top_contributors[2]["id"], user3.id)
        self.assertEqual(top_contributors[2]["total_contribution"]["rsc"], 75.0)
        self.assertEqual(top_contributors[2]["total_contribution"]["usd"], 0)
        self.assertEqual(len(top_contributors[2]["contributions"]), 1)

        # Verify individual contributions for user1 (who made multiple contributions)
        user1_contributions = top_contributors[1]["contributions"]
        self.assertEqual(len(user1_contributions), 2)

        # Verify contribution amounts (not checking order since it depends on implementation)
        contribution_amounts = [c["amount"] for c in user1_contributions]
        self.assertIn(50.0, contribution_amounts)
        self.assertIn(100.0, contribution_amounts)

    def test_create_contribution_closed_fundraise(self):
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Set fundraise status to closed
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        fundraise_obj.status = Fundraise.CLOSED
        fundraise_obj.save()

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(fundraise_id, user, amount=200)

        self.assertEqual(response.status_code, 400)

    def test_close_fundraise(self):
        """Test that a fundraise can be closed via the API"""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Create a contributor
        contributor = create_random_authenticated_user("fundraise_contributor")
        self._give_user_balance(contributor, 1000)

        # Make a contribution
        self._create_contribution(fundraise_id, contributor)

        # Verify fundraise is open
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        self.assertEqual(fundraise_obj.status, Fundraise.OPEN)

        # Call close endpoint
        self.client.force_authenticate(self.user)  # Need moderator permissions
        response = self.client.post(f"/api/fundraise/{fundraise_id}/close/")

        self.assertEqual(response.status_code, 200)

        # Verify fundraise is now closed
        fundraise_obj.refresh_from_db()
        self.assertEqual(fundraise_obj.status, Fundraise.CLOSED)

        # Verify escrow is cancelled and empty
        self.assertEqual(fundraise_obj.escrow.status, "CANCELLED")
        self.assertEqual(float(fundraise_obj.escrow.amount_holding), 0.0)

    def test_close_fundraise_not_moderator(self):
        """Test that only moderators can close a fundraise"""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Try to close with non-moderator
        regular_user = create_random_authenticated_user("regular_user")
        self.client.force_authenticate(regular_user)
        response = self.client.post(f"/api/fundraise/{fundraise_id}/close/")

        # Should get 403 Forbidden
        self.assertEqual(response.status_code, 403)

    def test_reopen_closed_fundraise(self):
        """A moderator can reopen a CLOSED fundraise with a duration."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        fundraise_obj.status = Fundraise.CLOSED
        fundraise_obj.save()
        fundraise_obj.escrow.set_cancelled_status()

        self.client.force_authenticate(self.user)
        before = datetime.now(pytz.UTC)
        response = self.client.post(
            f"/api/fundraise/{fundraise_id}/reopen/",
            {"duration_days": 14},
        )
        after = datetime.now(pytz.UTC)

        self.assertEqual(response.status_code, 200)

        fundraise_obj.refresh_from_db()
        self.assertEqual(fundraise_obj.status, Fundraise.OPEN)
        self.assertGreaterEqual(
            fundraise_obj.end_date, before + timedelta(days=14, seconds=-1)
        )
        self.assertLessEqual(
            fundraise_obj.end_date, after + timedelta(days=14, seconds=1)
        )
        # Escrow returned to PENDING so new contributions can land
        self.assertEqual(fundraise_obj.escrow.status, "PENDING")

    def test_reopen_expired_fundraise_extends_end_date(self):
        """Reopening an expired (but still OPEN) fundraise extends the end date."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        fundraise_obj.end_date = datetime.now(pytz.UTC) - timedelta(days=1)
        fundraise_obj.save()
        self.assertTrue(fundraise_obj.is_expired())

        self.client.force_authenticate(self.user)
        response = self.client.post(
            f"/api/fundraise/{fundraise_id}/reopen/",
            {"duration_days": 7},
        )

        self.assertEqual(response.status_code, 200)
        fundraise_obj.refresh_from_db()
        self.assertEqual(fundraise_obj.status, Fundraise.OPEN)
        self.assertFalse(fundraise_obj.is_expired())

    def test_reopen_completed_fundraise_fails(self):
        """Completed fundraises cannot be reopened; funds are already paid out."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        fundraise_obj.status = Fundraise.COMPLETED
        fundraise_obj.save()

        self.client.force_authenticate(self.user)
        response = self.client.post(
            f"/api/fundraise/{fundraise_id}/reopen/",
            {"duration_days": 30},
        )

        self.assertEqual(response.status_code, 400)
        fundraise_obj.refresh_from_db()
        self.assertEqual(fundraise_obj.status, Fundraise.COMPLETED)

    def test_reopen_fundraise_invalid_duration(self):
        """Non-positive or non-integer durations are rejected."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        self.client.force_authenticate(self.user)

        for bad in [0, -5, "abc", None]:
            payload = {} if bad is None else {"duration_days": bad}
            response = self.client.post(
                f"/api/fundraise/{fundraise_id}/reopen/",
                payload,
            )
            self.assertEqual(response.status_code, 400, msg=f"input={bad!r}")

    def test_reopen_fundraise_not_moderator(self):
        """Only moderators can reopen a fundraise."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        regular_user = create_random_authenticated_user("regular_user")
        self.client.force_authenticate(regular_user)
        response = self.client.post(
            f"/api/fundraise/{fundraise_id}/reopen/",
            {"duration_days": 14},
        )

        self.assertEqual(response.status_code, 403)

    def test_reopen_fundraise_allows_new_contributions(self):
        """After reopening a closed fundraise, new contributions should succeed."""
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Close the fundraise through the normal flow
        self.client.force_authenticate(self.user)
        self.client.post(f"/api/fundraise/{fundraise_id}/close/")

        # Reopen it
        response = self.client.post(
            f"/api/fundraise/{fundraise_id}/reopen/",
            {"duration_days": 30},
        )
        self.assertEqual(response.status_code, 200)

        # A contributor can now contribute
        contributor = create_random_authenticated_user("new_contributor")
        self._give_user_balance(contributor, 1000)
        contrib_response = self._create_contribution(
            fundraise_id, contributor, amount=100, use_credits=False
        )
        self.assertEqual(contrib_response.status_code, 200)

    def test_referral_bonuses_processed_on_fundraise_completion(self):
        """Test that referral bonuses are processed when a fundraise completes"""

        # Create a referrer and referred user
        referrer = create_random_authenticated_user("referrer")
        referred_user = create_random_authenticated_user("referred")

        # Create referral signup within 6 months
        ReferralSignup.objects.create(
            referrer=referrer,
            referred=referred_user,
            signup_date=datetime.now(pytz.UTC) - timedelta(days=30),  # 1 month ago
        )

        # Create a fundraise with a goal
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        # Give the referred user balance to contribute
        self._give_user_balance(referred_user, 1000)

        # Have the referred user contribute an amount that fulfills the goal
        response = self._create_contribution(
            fundraise_id,
            referred_user,
            amount=200,  # 200 RSC = 100 USD, fulfills goal
            use_credits=False,
        )

        self.assertEqual(response.status_code, 200)

        # Manually complete the fundraise as a moderator
        self.client.force_authenticate(self.user)  # self.user is a moderator
        response = self.client.post(f"/api/fundraise/{fundraise_id}/complete/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "COMPLETED")

        # Check that referral bonuses were created
        # Should create 2 distributions (one for referrer, one for referred user)
        # Note: Other distributions (fundraise payout, fees) are also created
        referral_bonus_distributions = Distribution.objects.filter(
            distribution_type="REFERRAL_BONUS",
            created_date__gte=datetime.now(pytz.UTC) - timedelta(seconds=10),
        )

        self.assertEqual(referral_bonus_distributions.count(), 2)

        # Check that both users received the correct bonus amount

        service = ReferralBonusService()
        expected_bonus = Decimal("200") * (service.bonus_percentage / 100)

        referrer_distribution = Distribution.objects.filter(
            recipient=referrer,
            distribution_type="REFERRAL_BONUS",
            amount=expected_bonus,
        ).first()
        self.assertIsNotNone(referrer_distribution)

        referred_distribution = Distribution.objects.filter(
            recipient=referred_user,
            distribution_type="REFERRAL_BONUS",
            amount=expected_bonus,
        ).first()
        self.assertIsNotNone(referred_distribution)

        # Check that locked balances were created
        referrer_balance = Balance.objects.filter(user=referrer, is_locked=True).first()
        self.assertIsNotNone(referrer_balance)
        self.assertEqual(float(referrer_balance.amount), expected_bonus)

        referred_balance = Balance.objects.filter(
            user=referred_user,
            is_locked=True,
        ).first()
        self.assertIsNotNone(referred_balance)
        self.assertEqual(float(referred_balance.amount), expected_bonus)

    def test_create_contribution_insufficient_credits(self):
        """
        With use_credits=True (the default), a contribution must fail when
        the user's locked balance alone cannot cover amount + fee, even if
        unlocked balance could cover the shortfall.
        """
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")

        Balance.objects.create(
            amount=30,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=False,
        )
        Balance.objects.create(
            amount=50,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
        )

        # Locked = 50, total cost = 109 → must fail without falling back to unlocked.
        response = self._create_contribution(fundraise_id, user, amount=100)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient funding credits", response.data["message"])

    def test_create_contribution_all_locked_balance(self):
        """
        Test contribution when all funds come from locked balance only.
        """
        # Arrange
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")

        # Give user only locked balance (enough for contribution + fees)
        Balance.objects.create(
            amount=200,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
        )

        # Verify user's balance situation
        regular_balance = user.get_balance()  # Should be 0
        total_balance = user.get_balance(include_locked=True)  # Should be 200
        locked_balance = user.get_locked_balance()  # Should be 200

        self.assertEqual(float(regular_balance), 0.0)
        self.assertEqual(float(total_balance), 200.0)
        self.assertEqual(float(locked_balance), 200.0)

        # Act
        response = self._create_contribution(fundraise_id, user, amount=100)

        # Assert
        self.assertEqual(response.status_code, 200)

        # Verify balance objects - should only have locked balance records
        purchase_content_type = ContentType.objects.get_for_model(Purchase)
        fee_content_type = ContentType.objects.get_for_model(BountyFee)

        # Should have 1 amount balance record: 100 from locked only
        amount_balances = Balance.objects.filter(
            user=user, content_type=purchase_content_type
        )
        self.assertEqual(amount_balances.count(), 1)

        locked_amount_balance = amount_balances.filter(is_locked=True).first()
        self.assertIsNotNone(locked_amount_balance)
        self.assertEqual(float(locked_amount_balance.amount), -100.0)

        # Should have 1 fee balance record: 9 from locked only
        fee_balances = Balance.objects.filter(user=user, content_type=fee_content_type)
        self.assertEqual(fee_balances.count(), 1)

        locked_fee_balance = fee_balances.filter(is_locked=True).first()
        self.assertIsNotNone(locked_fee_balance)
        self.assertEqual(float(locked_fee_balance.amount), -9.0)

    def test_create_contribution_use_credits_false_uses_only_unlocked(self):
        """
        When use_credits=False, the contribution must only debit the user's
        unlocked balance, even if they have locked funds available.
        """
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")

        # Enough unlocked to cover amount + fee on its own.
        Balance.objects.create(
            amount=200,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=False,
        )
        # Locked funds that would otherwise be consumed first.
        Balance.objects.create(
            amount=500,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
        )

        response = self._create_contribution(
            fundraise_id, user, amount=100, use_credits=False
        )

        self.assertEqual(response.status_code, 200)

        purchase_content_type = ContentType.objects.get_for_model(Purchase)
        fee_content_type = ContentType.objects.get_for_model(BountyFee)

        # Locked debits must not exist; unlocked must cover the full spend.
        self.assertFalse(
            Balance.objects.filter(
                user=user,
                content_type__in=[purchase_content_type, fee_content_type],
                is_locked=True,
            ).exists()
        )
        amount_balance = Balance.objects.get(
            user=user, content_type=purchase_content_type
        )
        self.assertEqual(float(amount_balance.amount), -100.0)
        self.assertFalse(amount_balance.is_locked)
        fee_balance = Balance.objects.get(user=user, content_type=fee_content_type)
        self.assertEqual(float(fee_balance.amount), -9.0)
        self.assertFalse(fee_balance.is_locked)

        # Locked balance is untouched.
        self.assertEqual(float(user.get_locked_balance()), 500.0)

    def test_create_contribution_use_credits_false_rejects_when_unlocked_short(self):
        """
        When use_credits=False, locked balance must not be spent even if the
        user's total (locked + unlocked) could otherwise cover the contribution.
        """
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")

        # Unlocked alone is insufficient.
        Balance.objects.create(
            amount=50,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=False,
        )
        # Locked would cover it if use_credits were True.
        Balance.objects.create(
            amount=200,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
        )

        response = self._create_contribution(
            fundraise_id, user, amount=100, use_credits=False
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient balance", response.data["message"])

    def test_complete_fundraise(self):
        """Test that a fundraise can be completed via the API by a moderator"""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        # Create a contributor
        contributor = create_random_authenticated_user("fundraise_contributor")
        self._give_user_balance(contributor, 1000)

        # Make a contribution that meets the goal
        self._create_contribution(
            fundraise_id, contributor, amount=200, use_credits=False
        )

        # Verify fundraise is still open
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        self.assertEqual(fundraise_obj.status, Fundraise.OPEN)

        # Call complete endpoint as moderator
        self.client.force_authenticate(self.user)  # Need moderator permissions
        response = self.client.post(f"/api/fundraise/{fundraise_id}/complete/")

        self.assertEqual(response.status_code, 200)

        # Verify fundraise is now completed
        fundraise_obj.refresh_from_db()
        self.assertEqual(fundraise_obj.status, Fundraise.COMPLETED)

        # Verify funds were paid out
        self.assertEqual(float(fundraise_obj.escrow.amount_holding), 0.0)
        self.assertEqual(float(fundraise_obj.escrow.amount_paid), 200.0)

        # Check that the owner was paid out
        owner_balance = Balance.objects.filter(user=self.user)
        self.assertEqual(owner_balance.count(), 1)
        self.assertEqual(float(owner_balance.first().amount), 200.0)

    def test_complete_fundraise_not_moderator(self):
        """Test that only moderators can complete a fundraise"""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Try to complete with non-moderator
        regular_user = create_random_authenticated_user("regular_user")
        self.client.force_authenticate(regular_user)
        response = self.client.post(f"/api/fundraise/{fundraise_id}/complete/")

        # Should get 403 Forbidden
        self.assertEqual(response.status_code, 403)

    def test_complete_fundraise_already_completed(self):
        """Test that a fundraise that's already completed can't be completed again"""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Set fundraise status to completed
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        fundraise_obj.status = Fundraise.COMPLETED
        fundraise_obj.save()

        # Try to complete
        self.client.force_authenticate(self.user)
        response = self.client.post(f"/api/fundraise/{fundraise_id}/complete/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("not open", response.data["message"])

    def test_complete_fundraise_no_funds(self):
        """Test that a fundraise with no funds can't be completed"""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Try to complete without any contributions
        self.client.force_authenticate(self.user)
        response = self.client.post(f"/api/fundraise/{fundraise_id}/complete/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("no funds to payout", response.data["message"])

    # USD Contribution Tests

    def _link_nonprofit(self, fundraise_id):
        nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit", endaoment_org_id="org_123"
        )
        fundraise = Fundraise.objects.get(id=fundraise_id)
        NonprofitFundraiseLink.objects.create(nonprofit=nonprofit, fundraise=fundraise)
        return nonprofit

    def test_create_usd_contribution(self):
        """Test creating a USD contribution to a fundraise."""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]
        self._link_nonprofit(fundraise_id)

        # Create contributor
        user = create_random_authenticated_user("usd_contributor")

        # Configure mock service
        self.mock_fundraise_service.create_contribution.return_value = (None, None)

        # Make USD contribution of $100 (10000 cents)
        view = FundraiseViewSet.as_view({"post": "create_contribution"})
        request = self.factory.post(
            f"/api/fundraise/{fundraise_id}/create_contribution/",
            {"amount": 10000, "amount_currency": "USD", "origin_fund_id": "fund_123"},
        )
        force_authenticate(request, user=user)
        response = view(
            request,
            pk=fundraise_id,
            fundraise_service=self.mock_fundraise_service,
        )

        self.assertEqual(response.status_code, 200)

        self.mock_fundraise_service.create_contribution.assert_called_once_with(
            user=user,
            fundraise=Fundraise.objects.get(id=fundraise_id),
            amount=10000,
            currency="USD",
            origin_fund_id="fund_123",
            use_credits=True,
        )

    def test_create_usd_contribution_requires_origin_fund_id(self):
        """Test that USD contributions require origin_fund_id."""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        # Create contributor
        user = create_random_authenticated_user("usd_contributor")

        # Try to contribute without origin_fund_id - should fail
        response = self._create_contribution(
            fundraise_id, user, amount=10000, amount_currency="USD"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("origin_fund_id is required", response.data["message"])

    def test_create_usd_contribution_below_minimum(self):
        """Test that USD contribution below minimum amount fails."""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]
        self._link_nonprofit(fundraise_id)

        # Create contributor
        user = create_random_authenticated_user("usd_contributor")

        # Try to contribute 50 cents (below $1 minimum)
        response = self._create_contribution(
            fundraise_id,
            user,
            amount=50,
            amount_currency="USD",
            origin_fund_id="fund_123",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid amount", response.data["message"])

    def test_create_usd_contribution_own_fundraise_no_nonprofit_fails(self):
        """Test that user cannot contribute USD to their own fundraise without a nonprofit."""
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        response = self._create_contribution(
            fundraise_id,
            self.user,
            amount=10000,
            amount_currency="USD",
            origin_fund_id="fund_123",
        )

        self.assertEqual(response.status_code, 400)

    def test_create_usd_contribution_own_fundraise_with_nonprofit(self):
        """Test that user CAN contribute USD to their own fundraise when a nonprofit is attached."""
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]
        self._link_nonprofit(fundraise_id)

        self.mock_fundraise_service.create_contribution.return_value = (None, None)

        view = FundraiseViewSet.as_view({"post": "create_contribution"})
        request = self.factory.post(
            f"/api/fundraise/{fundraise_id}/create_contribution/",
            {"amount": 10000, "amount_currency": "USD", "origin_fund_id": "fund_123"},
        )
        force_authenticate(request, user=self.user)
        response = view(
            request,
            pk=fundraise_id,
            fundraise_service=self.mock_fundraise_service,
        )

        self.assertEqual(response.status_code, 200)
        self.mock_fundraise_service.create_contribution.assert_called_once()

    def test_create_usd_contribution_closed_fundraise_fails(self):
        """Test that USD contribution to closed fundraise fails."""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]
        self._link_nonprofit(fundraise_id)

        # Close the fundraise
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        fundraise_obj.status = Fundraise.CLOSED
        fundraise_obj.save()

        # Create contributor
        user = create_random_authenticated_user("usd_contributor")

        # Try to contribute
        response = self._create_contribution(
            fundraise_id,
            user,
            amount=10000,
            amount_currency="USD",
            origin_fund_id="fund_123",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not open", response.data["message"])

    def test_create_usd_contribution_invalid_currency(self):
        """Test that contribution with invalid currency fails."""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        # Create contributor
        user = create_random_authenticated_user("contributor")
        self._give_user_balance(user, 10000)

        # Try to contribute with invalid currency
        response = self._create_contribution(
            fundraise_id, user, amount=100, amount_currency="INVALID"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("must be RSC or USD", response.data["message"])

    def _create_usd_contribution(
        self, fundraise_id, user, amount_cents=10000, fee_cents=900, **kwargs
    ):
        defaults = {
            "user": user,
            "fundraise_id": fundraise_id,
            "amount_cents": amount_cents,
            "fee_cents": fee_cents,
            "origin_fund_id": "fund_123",
            "destination_org_id": "org_123",
            "endaoment_transfer_id": "transfer_123",
            "status": UsdFundraiseContribution.Status.SUBMITTED,
        }
        defaults.update(kwargs)
        return UsdFundraiseContribution.objects.create(**defaults)

    def test_usd_contributions_csv_returns_csv(self):
        """
        Test that the endpoint returns a CSV with correct headers.
        """
        # Arrange
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        # Act
        self.client.force_authenticate(self.user)
        response = self.client.get(
            f"/api/fundraise/{fundraise_id}/usd_contributions.csv/"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn(
            f"fundraise_{fundraise_id}_usd_contributions.csv",
            response["Content-Disposition"],
        )

        content = response.content.decode()
        lines = content.strip().split("\n")
        headers = lines[0].split(",")
        self.assertEqual(headers, USD_CONTRIBUTION_CSV_HEADERS)

    def test_usd_contributions_csv_includes_contributions(self):
        """
        Test that CSV rows contain correct contribution data.
        """
        # Arrange
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]
        self._link_nonprofit(fundraise_id)

        contributor = create_random_authenticated_user("csv_contributor")
        self._create_usd_contribution(
            fundraise_id,
            contributor,
            amount_cents=50000,
            fee_cents=4500,
        )

        # Act
        self.client.force_authenticate(self.user)
        response = self.client.get(
            f"/api/fundraise/{fundraise_id}/usd_contributions.csv/"
        )

        # Assert
        content = response.content.decode()
        lines = content.strip().split("\n")
        self.assertEqual(len(lines), 2)  # header + 1 row

        row = lines[1].split(",")
        self.assertEqual(row[0], str(fundraise_id))  # fundraise_id
        self.assertEqual(row[4], "Test Nonprofit")  # nonprofit_name
        self.assertEqual(row[8], "500.00")  # amount_usd
        self.assertEqual(row[9], "45.00")  # fee_usd
        self.assertEqual(row[10], "455.00")  # net_amount_usd
        self.assertEqual(row[15], "SUBMITTED")  # status
        self.assertEqual(row[16], "False")  # is_refunded

    def test_usd_contributions_csv_requires_moderator(self):
        """
        Test that non-moderators cannot access the CSV endpoint.
        """
        # Arrange
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]
        regular_user = create_random_authenticated_user("regular_user")

        # Act
        self.client.force_authenticate(regular_user)
        response = self.client.get(
            f"/api/fundraise/{fundraise_id}/usd_contributions.csv/"
        )

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_usd_contributions_csv_not_found(self):
        """
        Test that a nonexistent fundraise returns 404.
        """
        # Act
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/fundraise/99999/usd_contributions.csv/")

        # Assert
        self.assertEqual(response.status_code, 404)

    # usd_contributions tests

    def test_usd_contributions_returns_only_authenticated_users(self):
        # Arrange
        fundraise_response = self._create_fundraise(self.post.id)
        fundraise_id = fundraise_response.data["id"]
        fundraise = Fundraise.objects.get(id=fundraise_id)

        contributor = create_random_authenticated_user("usd_contrib_user")
        other_user = create_random_authenticated_user("usd_contrib_other")

        UsdFundraiseContribution.objects.create(
            user=contributor,
            fundraise=fundraise,
            amount_cents=2500,
            fee_cents=225,
        )
        UsdFundraiseContribution.objects.create(
            user=other_user,
            fundraise=fundraise,
            amount_cents=9999,
        )

        # Act
        self.client.force_authenticate(contributor)
        response = self.client.get("/api/fundraise/usd_contributions/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        result = response.data["results"][0]
        self.assertEqual(result["fundraise"], fundraise_id)
        self.assertEqual(result["amount_cents"], 2500)
        self.assertEqual(result["amount_usd"], "25.00")
        self.assertEqual(result["fee_cents"], 225)
        self.assertEqual(result["fee_usd"], "2.25")
        # setUp creates an RscExchangeRate with rate=0.5 USD/RSC,
        # so $25.00 -> 50 RSC.
        self.assertEqual(result["rsc_usd_rate"], "0.5")
        self.assertEqual(result["amount_rsc"], "50.00")

    def test_usd_contributions_uses_historical_rsc_rate(self):
        # Arrange — record a newer exchange rate AFTER the contribution,
        # then verify the contribution serializes with the rate that was
        # in effect at its created_date, not the latest one.
        fundraise_response = self._create_fundraise(self.post.id)
        fundraise = Fundraise.objects.get(id=fundraise_response.data["id"])
        contributor = create_random_authenticated_user("usd_contrib_history")

        contribution = UsdFundraiseContribution.objects.create(
            user=contributor,
            fundraise=fundraise,
            amount_cents=1000,
        )
        # New rate created strictly after the contribution should not affect it.
        newer_rate = RscExchangeRate.objects.create(
            rate=2.0,
            real_rate=2.0,
            price_source="COIN_GECKO",
            target_currency="USD",
        )
        self.assertGreater(newer_rate.created_date, contribution.created_date)

        # Act
        self.client.force_authenticate(contributor)
        response = self.client.get("/api/fundraise/usd_contributions/")

        # Assert — historical rate of 0.5 from setUp, $10 -> 20 RSC.
        result = response.data["results"][0]
        self.assertEqual(result["rsc_usd_rate"], "0.5")
        self.assertEqual(result["amount_rsc"], "20.00")

    def test_usd_contributions_orders_most_recent_first(self):
        # Arrange
        fundraise_response = self._create_fundraise(self.post.id)
        fundraise = Fundraise.objects.get(id=fundraise_response.data["id"])
        contributor = create_random_authenticated_user("usd_contrib_order")

        older = UsdFundraiseContribution.objects.create(
            user=contributor, fundraise=fundraise, amount_cents=1000
        )
        newer = UsdFundraiseContribution.objects.create(
            user=contributor, fundraise=fundraise, amount_cents=2000
        )

        # Act
        self.client.force_authenticate(contributor)
        response = self.client.get("/api/fundraise/usd_contributions/")

        # Assert
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(ids, [newer.id, older.id])

    def test_usd_contributions_excludes_refunded(self):
        # Arrange
        fundraise_response = self._create_fundraise(self.post.id)
        fundraise = Fundraise.objects.get(id=fundraise_response.data["id"])
        contributor = create_random_authenticated_user("usd_contrib_refunded")

        kept = UsdFundraiseContribution.objects.create(
            user=contributor, fundraise=fundraise, amount_cents=500
        )
        UsdFundraiseContribution.objects.create(
            user=contributor,
            fundraise=fundraise,
            amount_cents=1000,
            is_refunded=True,
        )

        # Act
        self.client.force_authenticate(contributor)
        response = self.client.get("/api/fundraise/usd_contributions/")

        # Assert
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], kept.id)
