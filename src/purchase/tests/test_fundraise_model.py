from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Balance, Fundraise, Purchase
from purchase.related_models.constants.currency import ETHER, RSC, USD
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
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


class GetAmountRaisedTests(TestCase):
    """Tests for Fundraise.get_amount_raised() method."""

    def setUp(self):
        self.user = create_random_authenticated_user("fundraise_user", moderator=True)
        self.contributor = create_random_authenticated_user("contributor")

        # Create a post
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Set up service
        self.fundraise_service = FundraiseService()

        # Create a fundraise
        self.fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=self.post.unified_document,
            goal_amount=1000,
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

    def _create_usd_contribution(self, fundraise, user, amount_cents):
        """Helper method to create a USD contribution."""
        return UsdFundraiseContribution.objects.create(
            user=user,
            fundraise=fundraise,
            amount_cents=amount_cents,
            fee_cents=int(amount_cents * 0.09),
        )

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_usd_only(self, mock_exchange_rate):
        """Test get_amount_raised returns correct USD amount from USD contributions only."""
        mock_exchange_rate.return_value = 0.01  # 1 RSC = $0.01

        # Create USD contributions totaling $150 (15000 cents)
        self._create_usd_contribution(self.fundraise, self.contributor, 10000)  # $100
        self._create_usd_contribution(self.fundraise, self.contributor, 5000)  # $50

        amount = self.fundraise.get_amount_raised(currency=USD)

        self.assertEqual(amount, 150.0)

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_rsc_only(self, mock_exchange_rate):
        """Test get_amount_raised returns correct amount from RSC (escrow) only."""
        mock_exchange_rate.return_value = 0.01  # 1 RSC = $0.01

        # Add RSC to escrow (no USD contributions)
        self.fundraise.escrow.amount_holding = 500
        self.fundraise.escrow.save()

        amount_usd = self.fundraise.get_amount_raised(currency=USD)
        amount_rsc = self.fundraise.get_amount_raised(currency=RSC)

        # 500 RSC * $0.01 = $5
        self.assertEqual(amount_usd, 5.0)
        # RSC amount should be the escrow amount
        self.assertEqual(amount_rsc, 500.0)

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_combined_rsc_and_usd(self, mock_exchange_rate):
        """Test get_amount_raised combines RSC and USD contributions correctly."""
        mock_exchange_rate.return_value = 0.01  # 1 RSC = $0.01

        # Add RSC to escrow
        self.fundraise.escrow.amount_holding = 1000  # 1000 RSC = $10
        self.fundraise.escrow.save()

        # Add USD contributions
        self._create_usd_contribution(self.fundraise, self.contributor, 5000)  # $50

        amount_usd = self.fundraise.get_amount_raised(currency=USD)

        # $10 (from RSC) + $50 (from USD) = $60
        self.assertEqual(amount_usd, 60.0)

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_in_rsc_currency(self, mock_exchange_rate):
        """Test get_amount_raised returns correct RSC amount with USD contributions."""
        mock_exchange_rate.return_value = 0.01  # 1 RSC = $0.01

        # Add RSC to escrow
        self.fundraise.escrow.amount_holding = 1000
        self.fundraise.escrow.save()

        # Add USD contributions ($50 = 5000 RSC at $0.01/RSC)
        self._create_usd_contribution(self.fundraise, self.contributor, 5000)  # $50

        amount_rsc = self.fundraise.get_amount_raised(currency=RSC)

        # 1000 RSC + 5000 RSC (from $50) = 6000 RSC
        self.assertEqual(amount_rsc, 6000.0)

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_no_contributions(self, mock_exchange_rate):
        """Test get_amount_raised returns 0 when there are no contributions."""
        mock_exchange_rate.return_value = 0.01

        amount = self.fundraise.get_amount_raised(currency=USD)

        self.assertEqual(amount, 0.0)

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_multiple_usd_contributors(self, mock_exchange_rate):
        """Test get_amount_raised sums contributions from multiple users."""
        mock_exchange_rate.return_value = 0.01

        contributor2 = create_random_authenticated_user("contributor2")
        contributor3 = create_random_authenticated_user("contributor3")

        self._create_usd_contribution(self.fundraise, self.contributor, 10000)  # $100
        self._create_usd_contribution(self.fundraise, contributor2, 5000)  # $50
        self._create_usd_contribution(self.fundraise, contributor3, 2500)  # $25

        amount = self.fundraise.get_amount_raised(currency=USD)

        self.assertEqual(amount, 175.0)

    @patch(
        "purchase.related_models.fundraise_model.RscExchangeRate.rsc_to_eth",
        return_value=0.0005,
    )
    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_in_ether_currency(
        self, mock_exchange_rate, mock_rsc_to_eth
    ):
        """Test get_amount_raised returns correct ETHER amount."""
        mock_exchange_rate.return_value = 0.01  # 1 RSC = $0.01

        # Add RSC to escrow
        self.fundraise.escrow.amount_holding = 1000
        self.fundraise.escrow.save()

        # Add USD contributions
        self._create_usd_contribution(self.fundraise, self.contributor, 5000)  # $50

        amount_eth = self.fundraise.get_amount_raised(currency=ETHER)

        # The method converts both RSC and USD to ETH
        # We're mocking rsc_to_eth to return 0.0005, and it gets called twice
        self.assertEqual(amount_eth, 0.001)

    def test_get_amount_raised_invalid_currency(self):
        """Test get_amount_raised raises ValueError for invalid currency."""
        with self.assertRaises(ValueError) as context:
            self.fundraise.get_amount_raised(currency="INVALID")

        self.assertEqual(str(context.exception), "Invalid currency")


class CloseFundraiseUsdTests(TestCase):
    """Tests for USD refunds when closing a fundraise."""

    def setUp(self):
        self.user = create_random_authenticated_user("fundraise_model", moderator=True)

        # Create revenue account for fee refunds
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

    def _create_usd_contribution(self, fundraise, user, amount_cents, fee_cents=None):
        """Helper method to create a USD contribution."""
        if fee_cents is None:
            fee_cents = int(amount_cents * 0.09)
        return UsdFundraiseContribution.objects.create(
            user=user,
            fundraise=fundraise,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
        )

    def _give_user_usd_balance(self, user, amount_cents):
        """Helper method to give a user USD balance."""
        from purchase.related_models.usd_balance_model import UsdBalance

        UsdBalance.objects.create(user=user, amount_cents=amount_cents)

    def test_close_fundraise_refunds_usd_contributions(self):
        """Test that closing a fundraise refunds USD contributions."""
        contributor = create_random_authenticated_user("usd_contributor")

        # Give user initial balance and create contribution
        self._give_user_usd_balance(contributor, 10000)  # $100
        initial_balance = contributor.get_usd_balance_cents()

        # Create USD contribution: $50 + $4.50 fee = $54.50 total
        contribution = self._create_usd_contribution(
            self.fundraise, contributor, amount_cents=5000, fee_cents=450
        )

        # Verify is_refunded starts as False
        self.assertFalse(contribution.is_refunded)

        # Simulate the deduction that would have happened when contributing
        contributor.decrease_usd_balance(5450, source=contribution)
        balance_after_contribution = contributor.get_usd_balance_cents()
        self.assertEqual(balance_after_contribution, 10000 - 5450)  # $45.50

        # Close the fundraise
        result = self.fundraise.close_fundraise()

        # Check result
        self.assertTrue(result)

        # Verify contributor got refunded (contribution + fee)
        final_balance = contributor.get_usd_balance_cents()
        self.assertEqual(final_balance, initial_balance)  # Back to $100

        # Verify is_refunded is now True
        contribution.refresh_from_db()
        self.assertTrue(contribution.is_refunded)

    def test_close_fundraise_refunds_multiple_usd_contributors(self):
        """Test that closing a fundraise refunds multiple USD contributors."""
        contributor1 = create_random_authenticated_user("usd_contributor1")
        contributor2 = create_random_authenticated_user("usd_contributor2")

        # Give users initial balances
        self._give_user_usd_balance(contributor1, 20000)  # $200
        self._give_user_usd_balance(contributor2, 15000)  # $150

        initial_balance1 = contributor1.get_usd_balance_cents()
        initial_balance2 = contributor2.get_usd_balance_cents()

        # Create USD contributions
        contribution1 = self._create_usd_contribution(
            self.fundraise, contributor1, amount_cents=10000, fee_cents=900
        )
        contribution2 = self._create_usd_contribution(
            self.fundraise, contributor2, amount_cents=5000, fee_cents=450
        )

        # Simulate deductions
        contributor1.decrease_usd_balance(10900, source=contribution1)
        contributor2.decrease_usd_balance(5450, source=contribution2)

        # Close the fundraise
        result = self.fundraise.close_fundraise()

        # Check result
        self.assertTrue(result)

        # Verify both contributors got refunded
        self.assertEqual(contributor1.get_usd_balance_cents(), initial_balance1)
        self.assertEqual(contributor2.get_usd_balance_cents(), initial_balance2)

    def test_close_fundraise_refunds_both_rsc_and_usd(self):
        """Test that closing a fundraise refunds both RSC and USD contributions."""
        from django.contrib.contenttypes.models import ContentType

        rsc_contributor = create_random_authenticated_user("rsc_contributor")
        usd_contributor = create_random_authenticated_user("usd_contributor")

        # Give RSC contributor balance
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount=1000, user=rsc_contributor, content_type=DISTRIBUTION_CONTENT_TYPE
        )

        # Create RSC contribution
        Purchase.objects.create(
            user=rsc_contributor,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=100,
        )
        self.fundraise.escrow.amount_holding += 100
        self.fundraise.escrow.save()

        # Give USD contributor balance and create contribution
        self._give_user_usd_balance(usd_contributor, 10000)
        initial_usd_balance = usd_contributor.get_usd_balance_cents()

        contribution = self._create_usd_contribution(
            self.fundraise, usd_contributor, amount_cents=5000, fee_cents=450
        )
        usd_contributor.decrease_usd_balance(5450, source=contribution)

        # Close the fundraise
        result = self.fundraise.close_fundraise()

        # Check result
        self.assertTrue(result)

        # Verify RSC contributor got refunded
        rsc_refund = Balance.objects.filter(user=rsc_contributor, amount=100).exists()
        self.assertTrue(rsc_refund)

        # Verify USD contributor got refunded
        self.assertEqual(usd_contributor.get_usd_balance_cents(), initial_usd_balance)

    def test_close_fundraise_no_usd_contributions(self):
        """Test that closing a fundraise with no USD contributions works."""
        # Close the fundraise (no USD contributions exist)
        result = self.fundraise.close_fundraise()

        # Check it succeeded
        self.assertTrue(result)
        self.fundraise.refresh_from_db()
        self.assertEqual(self.fundraise.status, Fundraise.CLOSED)

    def test_close_fundraise_skips_already_refunded_contributions(self):
        """Test that already refunded USD contributions are not refunded again."""
        contributor = create_random_authenticated_user("usd_contributor")

        # Give user balance and create contribution
        self._give_user_usd_balance(contributor, 10000)
        contribution = self._create_usd_contribution(
            self.fundraise, contributor, amount_cents=5000, fee_cents=450
        )
        contributor.decrease_usd_balance(5450, source=contribution)

        # Manually mark as refunded and give a manual refund
        contribution.is_refunded = True
        contribution.save()
        contributor.increase_usd_balance(5450, source=contribution)
        balance_after_manual_refund = contributor.get_usd_balance_cents()

        # Close the fundraise
        self.fundraise.close_fundraise()

        # Verify balance hasn't changed (no double refund)
        final_balance = contributor.get_usd_balance_cents()
        self.assertEqual(final_balance, balance_after_manual_refund)
