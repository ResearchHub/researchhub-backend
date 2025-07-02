from datetime import datetime, timedelta
from decimal import Decimal

import pytz
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from purchase.models import Balance, Fundraise, Purchase, RscExchangeRate
from purchase.services.fundraise_service import FundraiseService
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
        self.fundraise_service = FundraiseService()

        # Initialize the view with the service
        self.view = FundraiseViewSet(fundraise_service=self.fundraise_service)

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
        response = self._create_contribution(fundraise_id, user, amount=50)
        response = self._create_contribution(fundraise_id, user, amount=50)

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
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        response = self._create_contribution(fundraise_id, self.user)

        self.assertEqual(response.status_code, 400)

    def test_create_contribution_exceeds_goal(self):
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")
        self._give_user_balance(user, 1000)
        response = self._create_contribution(
            fundraise_id, user, amount=200
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
        self._create_contribution(fundraise_id, user1, amount=100)
        self._create_contribution(fundraise_id, user1, amount=50)
        self._create_contribution(fundraise_id, user2, amount=200)
        self._create_contribution(fundraise_id, user3, amount=75)

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
        self.assertEqual(top_contributors[0]["total_contribution"], 200.0)
        self.assertEqual(len(top_contributors[0]["contributions"]), 1)

        # User1 should be second (150 RSC total)
        self.assertEqual(top_contributors[1]["id"], user1.id)
        self.assertEqual(top_contributors[1]["total_contribution"], 150.0)
        self.assertEqual(len(top_contributors[1]["contributions"]), 2)

        # User3 should be third (75 RSC)
        self.assertEqual(top_contributors[2]["id"], user3.id)
        self.assertEqual(top_contributors[2]["total_contribution"], 75.0)
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
            fundraise_id, referred_user, amount=200  # 200 RSC = 100 USD, fulfills goal
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
            distribution_type=Balance.LockType.REFERRAL_BONUS,
            created_date__gte=datetime.now(pytz.UTC) - timedelta(seconds=10),
        )

        self.assertEqual(referral_bonus_distributions.count(), 2)

        # Check that both users received the correct bonus amount

        expected_bonus = Decimal("200") * (
            ReferralBonusService().bonus_percentage / 100
        )

        referrer_distribution = Distribution.objects.filter(
            recipient=referrer,
            distribution_type=Balance.LockType.REFERRAL_BONUS,
            amount=expected_bonus,
        ).first()
        self.assertIsNotNone(referrer_distribution)

        referred_distribution = Distribution.objects.filter(
            recipient=referred_user,
            distribution_type=Balance.LockType.REFERRAL_BONUS,
            amount=expected_bonus,
        ).first()
        self.assertIsNotNone(referred_distribution)

        # Check that locked balances were created
        referrer_balance = Balance.objects.filter(
            user=referrer, is_locked=True, lock_type=Balance.LockType.REFERRAL_BONUS
        ).first()
        self.assertIsNotNone(referrer_balance)
        self.assertEqual(float(referrer_balance.amount), expected_bonus)

        referred_balance = Balance.objects.filter(
            user=referred_user,
            is_locked=True,
            lock_type=Balance.LockType.REFERRAL_BONUS,
        ).first()
        self.assertIsNotNone(referred_balance)
        self.assertEqual(float(referred_balance.amount), expected_bonus)

    def test_create_contribution_with_locked_balance(self):
        """
        Test that locked balance can be used for fundraise contributions.
        """
        # Arrange
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")

        # Regular balance (not enough for contribution + fees)
        Balance.objects.create(
            amount=50,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=False,
        )

        # Locked balance (enough to cover the shortfall)
        Balance.objects.create(
            amount=100,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
            lock_type=Balance.LockType.REFERRAL_BONUS,
        )

        # Verify user's balance situation
        regular_balance = user.get_balance()  # Should be 50
        total_balance = user.get_balance(include_locked=True)  # Should be 150
        locked_balance = user.get_locked_balance()  # Should be 100

        self.assertEqual(float(regular_balance), 50.0)
        self.assertEqual(float(total_balance), 150.0)
        self.assertEqual(float(locked_balance), 100.0)

        # Act
        # Try to contribute 100 RSC (which would cost 100 + 9 fees = 109 total)
        # This should succeed because total balance (150) >= cost (109)
        # even though unlocked balance (50) < cost (109)
        response = self._create_contribution(fundraise_id, user, amount=100)

        # Assert
        self.assertEqual(response.status_code, 200)

        updated_fundraise = response.data
        self.assertEqual(updated_fundraise["amount_raised"]["rsc"], 100)
        self.assertEqual(float(updated_fundraise["escrow"]["amount_holding"]), 100.0)

        # Verify balance objects were created with proper locked/unlocked split
        purchase_content_type = ContentType.objects.get_for_model(Purchase)
        fee_content_type = ContentType.objects.get_for_model(BountyFee)

        # Should have 1 amount balance record: 100 from locked (locked used first)
        amount_balances = Balance.objects.filter(
            user=user, content_type=purchase_content_type
        )
        self.assertEqual(amount_balances.count(), 1)

        # Check locked amount balance (should be -100, all from locked)
        locked_amount_balance = amount_balances.filter(is_locked=True).first()
        self.assertIsNotNone(locked_amount_balance)
        self.assertEqual(float(locked_amount_balance.amount), -100.0)
        self.assertEqual(
            locked_amount_balance.lock_type, Balance.LockType.REFERRAL_BONUS
        )

        # Should have 1 fee balance record: 9 from regular (no locked left)
        fee_balances = Balance.objects.filter(user=user, content_type=fee_content_type)
        self.assertEqual(fee_balances.count(), 1)

        # Check regular fee balance (should be -9, from regular balance)
        regular_fee_balance = fee_balances.filter(is_locked=False).first()
        self.assertIsNotNone(regular_fee_balance)
        self.assertEqual(float(regular_fee_balance.amount), -9.0)

    def test_create_contribution_insufficient_total_balance(self):
        """
        Test that contribution fails if total balance (including locked) is
        insufficient.
        """
        # Arrange
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")

        # Regular balance
        Balance.objects.create(
            amount=30,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=False,
        )

        # Locked balance
        Balance.objects.create(
            amount=50,
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
            lock_type=Balance.LockType.REFERRAL_BONUS,
        )

        # Total balance is 80, but contribution of 100 + 9 fees = 109 total cost
        total_balance = user.get_balance(include_locked=True)
        self.assertEqual(float(total_balance), 80.0)

        # Act
        response = self._create_contribution(fundraise_id, user, amount=100)

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient balance", response.data["message"])

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
            lock_type=Balance.LockType.REFERRAL_BONUS,
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

    def test_create_contribution_mixed_balance_split(self):
        """
        Test contribution when locked balance is insufficient, forcing a split.
        """
        # Arrange
        fundraise = self._create_fundraise(self.post.id)
        fundraise_id = fundraise.data["id"]

        user = create_random_authenticated_user("fundraise_views")

        # Give user partial locked balance (insufficient for full contribution)
        Balance.objects.create(
            amount=60,  # Less than 100 RSC contribution
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
            lock_type=Balance.LockType.REFERRAL_BONUS,
        )

        # Give user regular balance to cover the rest
        Balance.objects.create(
            amount=60,  # Enough to cover remaining amount + fees
            user=user,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=False,
        )

        # Total: 120 RSC (60 locked + 60 regular)
        # Need: 109 RSC (100 contribution + 9 fees)

        # Act
        response = self._create_contribution(fundraise_id, user, amount=100)

        # Assert
        self.assertEqual(response.status_code, 200)

        # Verify balance objects show proper split
        purchase_content_type = ContentType.objects.get_for_model(Purchase)
        fee_content_type = ContentType.objects.get_for_model(BountyFee)

        # Should have 2 amount balance records: 60 locked + 40 regular
        amount_balances = Balance.objects.filter(
            user=user, content_type=purchase_content_type
        )
        self.assertEqual(amount_balances.count(), 2)

        # Check locked amount balance (should be -60)
        locked_amount_balance = amount_balances.filter(is_locked=True).first()
        self.assertIsNotNone(locked_amount_balance)
        self.assertEqual(float(locked_amount_balance.amount), -60.0)

        # Check regular amount balance (should be -40)
        regular_amount_balance = amount_balances.filter(is_locked=False).first()
        self.assertIsNotNone(regular_amount_balance)
        self.assertEqual(float(regular_amount_balance.amount), -40.0)

        # Should have 1 fee balance record: 9 from regular (no locked left)
        fee_balances = Balance.objects.filter(user=user, content_type=fee_content_type)
        self.assertEqual(fee_balances.count(), 1)

        # Check regular fee balance (should be -9)
        regular_fee_balance = fee_balances.filter(is_locked=False).first()
        self.assertIsNotNone(regular_fee_balance)
        self.assertEqual(float(regular_fee_balance.amount), -9.0)

    def test_complete_fundraise(self):
        """Test that a fundraise can be completed via the API by a moderator"""
        # Create a fundraise
        fundraise = self._create_fundraise(self.post.id, goal_amount=100)
        fundraise_id = fundraise.data["id"]

        # Create a contributor
        contributor = create_random_authenticated_user("fundraise_contributor")
        self._give_user_balance(contributor, 1000)

        # Make a contribution that meets the goal
        self._create_contribution(fundraise_id, contributor, amount=200)

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
