from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Balance, Fundraise, Purchase
from purchase.services.fundraise_service import FundraiseService
from reputation.models import BountyFee
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user


class FundraiseModelTests(TestCase):
    def setUp(self):
        # Create a moderator user
        self.user = create_random_authenticated_user("fundraise_model", moderator=True)

        # Create revenue account that will be used for fee refunds
        self.revenue_account = create_random_authenticated_user("revenue_account")
        self.revenue_account.email = "revenue@researchhub.com"
        self.revenue_account.save()

        # Create a post
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Set up service
        self.fundraise_service = FundraiseService()

        # Create a fundraise
        self.fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=100,
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Set up bounty fee for calculations
        self.bounty_fee = BountyFee.objects.create(rh_pct=0.07, dao_pct=0.02)

    def _create_contribution(self, fundraise, user, amount=100):
        """Helper method to create a contribution to a fundraise"""
        # Create a purchase (contribution)
        purchase = Purchase.objects.create(
            user=user,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=amount,
        )

        # Add amount to escrow
        fundraise.escrow.amount_holding += amount
        fundraise.escrow.save()

        return purchase

    def _give_user_balance(self, user, amount):
        """Helper method to give a user balance"""
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount=amount, user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )

    def test_close_fundraise_success(self):
        """Test that a fundraise can be successfully closed"""
        # Create a contributor
        contributor = create_random_authenticated_user("fundraise_contributor")
        self._give_user_balance(contributor, 1000)

        # Create a contribution
        self._create_contribution(self.fundraise, contributor, amount=100)

        # Check initial state
        self.assertEqual(self.fundraise.status, Fundraise.OPEN)
        self.assertEqual(self.fundraise.escrow.amount_holding, 100)

        # Close the fundraise
        result = self.fundraise.close_fundraise()

        # Check result
        self.assertTrue(result)

        # Verify fundraise status was updated
        self.fundraise.refresh_from_db()
        self.assertEqual(self.fundraise.status, Fundraise.CLOSED)

        # Verify escrow status was updated
        self.assertEqual(self.fundraise.escrow.status, "CANCELLED")

        # Verify escrow amount is now 0
        self.assertEqual(self.fundraise.escrow.amount_holding, 0)

        # Verify contributor got refunded (check Balance records)
        refund_balance = Balance.objects.filter(
            user=contributor, amount=100  # Look for positive balance (refund)
        ).exists()
        self.assertTrue(refund_balance)

    def test_close_fundraise_multiple_contributors(self):
        """Test that a fundraise with multiple contributors can be closed"""
        # Create contributors
        contributor1 = create_random_authenticated_user("contributor1")
        contributor2 = create_random_authenticated_user("contributor2")
        contributor3 = create_random_authenticated_user("contributor3")

        self._give_user_balance(contributor1, 1000)
        self._give_user_balance(contributor2, 1000)
        self._give_user_balance(contributor3, 1000)

        # Create contributions
        self._create_contribution(self.fundraise, contributor1, amount=50)
        self._create_contribution(self.fundraise, contributor2, amount=30)
        self._create_contribution(self.fundraise, contributor3, amount=20)

        # Close the fundraise
        result = self.fundraise.close_fundraise()

        # Check result
        self.assertTrue(result)

        # Verify fundraise status was updated
        self.fundraise.refresh_from_db()
        self.assertEqual(self.fundraise.status, Fundraise.CLOSED)

        # Verify each contributor got their money back
        refund1 = Balance.objects.filter(user=contributor1, amount=50).exists()
        refund2 = Balance.objects.filter(user=contributor2, amount=30).exists()
        refund3 = Balance.objects.filter(user=contributor3, amount=20).exists()

        self.assertTrue(refund1)
        self.assertTrue(refund2)
        self.assertTrue(refund3)

    def test_close_fundraise_already_closed(self):
        """Test that a fundraise that's already closed can't be closed again"""
        # Set fundraise status to closed
        self.fundraise.status = Fundraise.CLOSED
        self.fundraise.save()

        # Attempt to close
        result = self.fundraise.close_fundraise()

        # Check it failed
        self.assertFalse(result)

    def test_close_fundraise_completed(self):
        """Test that a completed fundraise can't be closed"""
        # Set fundraise status to completed
        self.fundraise.status = Fundraise.COMPLETED
        self.fundraise.save()

        # Attempt to close
        result = self.fundraise.close_fundraise()

        # Check it failed
        self.assertFalse(result)

    def test_close_fundraise_no_escrow_funds(self):
        """Test that a fundraise with no escrow funds can be closed"""
        # Set escrow amount to 0
        self.fundraise.escrow.amount_holding = 0
        self.fundraise.escrow.save()

        # Attempt to close
        result = self.fundraise.close_fundraise()

        # Check it succeeded
        self.assertTrue(result)
        # Verify status changed to CLOSED
        self.fundraise.refresh_from_db()
        self.assertEqual(self.fundraise.status, self.fundraise.CLOSED)

    def test_close_fundraise_refunds_fees(self):
        """Test that closing a fundraise also refunds the fees that were deducted"""
        from decimal import Decimal

        from reputation.utils import calculate_bounty_fees

        # Create a contributor
        contributor = create_random_authenticated_user("fundraise_contributor")
        self._give_user_balance(contributor, 1000)

        # Create a contribution
        contribution_amount = Decimal("100")
        self._create_contribution(
            self.fundraise, contributor, amount=contribution_amount
        )

        # Calculate what the fee would be for this contribution
        fee, rh_fee, dao_fee, fee_object = calculate_bounty_fees(contribution_amount)

        # Get initial balance count for contributor
        initial_balance_count = Balance.objects.filter(user=contributor).count()

        # Close the fundraise
        result = self.fundraise.close_fundraise()

        # Check result
        self.assertTrue(result)

        # Verify that new positive balance records were created (refunds)
        final_balance_count = Balance.objects.filter(user=contributor).count()
        # Should have at least 2 new records: one for contribution refund,
        # one for fee refund
        self.assertGreater(final_balance_count, initial_balance_count)

        # Verify that a positive balance record exists for the fee refund
        fee_refund_exists = Balance.objects.filter(
            user=contributor,
            amount=fee.to_eng_string(),  # Positive amount (refund)
        ).exists()
        self.assertTrue(fee_refund_exists)
