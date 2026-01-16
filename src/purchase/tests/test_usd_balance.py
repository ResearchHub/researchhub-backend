from rest_framework.test import APITestCase

from purchase.models import Fundraise, UsdBalance, UsdFundraiseContribution
from purchase.services.fundraise_service import FundraiseService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user


class UsdFundraiseContributionTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("mod_user", moderator=True)
        self.contributor = create_random_authenticated_user("contributor")
        self.post = create_post(
            created_by=self.moderator, document_type=PREREGISTRATION
        )
        self.fundraise_service = FundraiseService()

    def _create_fundraise(self, user=None, goal_amount=10000):
        if user is None:
            user = self.moderator
        self.client.force_authenticate(self.moderator)
        return self.client.post(
            "/api/fundraise/",
            {
                "post_id": self.post.id,
                "recipient_user_id": user.id,
                "goal_amount": goal_amount,
                "goal_currency": "USD",
            },
        )

    def _give_usd_balance(self, user, amount_cents):
        UsdBalance.objects.create(
            user=user,
            amount_cents=amount_cents,
            description="Test deposit",
        )

    def _contribute_usd(self, fundraise_id, user, amount_cents):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/api/fundraise/{fundraise_id}/contribute_usd/",
            {"amount_cents": amount_cents},
        )

    def test_contribute_usd_success(self):
        """Test successful USD contribution to fundraise."""
        fundraise = self._create_fundraise()
        fundraise_id = fundraise.data["id"]

        self._give_usd_balance(self.contributor, 20000)  # $200

        response = self._contribute_usd(fundraise_id, self.contributor, 10000)  # $100

        self.assertEqual(response.status_code, 200)

        # Check fundraise was updated
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        self.assertEqual(fundraise_obj.usd_amount_raised_cents, 10000)

        # Check contribution record was created
        contribution = UsdFundraiseContribution.objects.get(
            user=self.contributor, fundraise_id=fundraise_id
        )
        self.assertEqual(contribution.amount_cents, 10000)
        self.assertEqual(contribution.fee_cents, 900)  # 9% of $100

        # Check balance was deducted (amount + fee)
        balance = self.contributor.get_usd_balance_cents()
        self.assertEqual(balance, 20000 - 10000 - 900)  # $200 - $100 - $9 = $91

    def test_contribute_usd_minimum_amount(self):
        """Test that minimum contribution is $1 (100 cents)."""
        fundraise = self._create_fundraise()
        fundraise_id = fundraise.data["id"]

        self._give_usd_balance(self.contributor, 10000)

        # Try to contribute less than $1
        response = self._contribute_usd(fundraise_id, self.contributor, 99)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Minimum contribution", response.data["message"])

    def test_contribute_usd_insufficient_balance(self):
        """Test contribution fails with insufficient balance."""
        fundraise = self._create_fundraise()
        fundraise_id = fundraise.data["id"]

        self._give_usd_balance(self.contributor, 1000)  # $10

        # Try to contribute more than balance (including fees)
        response = self._contribute_usd(fundraise_id, self.contributor, 1000)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient USD balance", response.data["message"])

    def test_contribute_usd_to_own_fundraise(self):
        """Test that users cannot contribute to their own fundraise."""
        fundraise = self._create_fundraise(user=self.moderator)
        fundraise_id = fundraise.data["id"]

        self._give_usd_balance(self.moderator, 20000)

        response = self._contribute_usd(fundraise_id, self.moderator, 10000)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot contribute to your own", response.data["message"])

    def test_contribute_usd_closed_fundraise(self):
        """Test contribution fails for closed fundraise."""
        fundraise = self._create_fundraise()
        fundraise_id = fundraise.data["id"]

        # Close the fundraise
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        fundraise_obj.status = Fundraise.CLOSED
        fundraise_obj.save()

        self._give_usd_balance(self.contributor, 20000)

        response = self._contribute_usd(fundraise_id, self.contributor, 10000)

        self.assertEqual(response.status_code, 400)
        self.assertIn("not open", response.data["message"])

    def test_contribute_usd_nonexistent_fundraise(self):
        """Test contribution fails for nonexistent fundraise."""
        self._give_usd_balance(self.contributor, 20000)

        response = self._contribute_usd(99999, self.contributor, 10000)

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not exist", response.data["message"])

    def test_contribute_usd_multiple_contributions(self):
        """Test multiple contributions from same user."""
        fundraise = self._create_fundraise()
        fundraise_id = fundraise.data["id"]

        self._give_usd_balance(self.contributor, 50000)  # $500

        # Make first contribution
        response1 = self._contribute_usd(fundraise_id, self.contributor, 10000)
        self.assertEqual(response1.status_code, 200)

        # Make second contribution
        response2 = self._contribute_usd(fundraise_id, self.contributor, 5000)
        self.assertEqual(response2.status_code, 200)

        # Check total raised
        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        self.assertEqual(fundraise_obj.usd_amount_raised_cents, 15000)

        # Check contribution records
        contributions = UsdFundraiseContribution.objects.filter(
            user=self.contributor, fundraise_id=fundraise_id
        )
        self.assertEqual(contributions.count(), 2)

    def test_contribute_usd_fee_calculation(self):
        """Test that 9% fee is correctly calculated."""
        fundraise = self._create_fundraise()
        fundraise_id = fundraise.data["id"]

        self._give_usd_balance(self.contributor, 100000)

        # Contribute $100
        response = self._contribute_usd(fundraise_id, self.contributor, 10000)
        self.assertEqual(response.status_code, 200)

        contribution = UsdFundraiseContribution.objects.get(
            user=self.contributor, fundraise_id=fundraise_id
        )
        self.assertEqual(contribution.fee_cents, 900)  # 9% of $100 = $9

        # Check balance deduction
        balance_record = UsdBalance.objects.filter(
            user=self.contributor, amount_cents__lt=0
        ).first()
        self.assertEqual(balance_record.amount_cents, -10900)  # $100 + $9 fee

    def test_get_usd_contributors(self):
        """Test the get_usd_contributors method on Fundraise."""
        fundraise = self._create_fundraise()
        fundraise_id = fundraise.data["id"]

        # Create multiple contributors
        contributor2 = create_random_authenticated_user("contributor2")

        self._give_usd_balance(self.contributor, 20000)
        self._give_usd_balance(contributor2, 20000)

        self._contribute_usd(fundraise_id, self.contributor, 10000)
        self._contribute_usd(fundraise_id, contributor2, 5000)

        fundraise_obj = Fundraise.objects.get(id=fundraise_id)
        contributors = fundraise_obj.get_usd_contributors()

        self.assertEqual(contributors.count(), 2)


class UserUsdBalanceMethodTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("balance_test_user")

    def test_get_usd_balance_cents_empty(self):
        """Test get_usd_balance_cents returns 0 when no balance exists."""
        balance = self.user.get_usd_balance_cents()
        self.assertEqual(balance, 0)

    def test_get_usd_balance_cents_with_records(self):
        """Test get_usd_balance_cents aggregates all balance records."""
        UsdBalance.objects.create(user=self.user, amount_cents=10000)
        UsdBalance.objects.create(user=self.user, amount_cents=5000)
        UsdBalance.objects.create(user=self.user, amount_cents=-2000)

        balance = self.user.get_usd_balance_cents()
        self.assertEqual(balance, 13000)  # $100 + $50 - $20 = $130
