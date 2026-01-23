from unittest.mock import patch

from django.test import TestCase

from purchase.models import Fundraise
from purchase.related_models.constants.currency import ETHER, RSC, USD
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.services.fundraise_service import FundraiseService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_authenticated_user


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

    @patch(
        "purchase.related_models.rsc_exchange_rate_model.RscExchangeRate.get_latest_exchange_rate"
    )
    def test_get_amount_raised_excludes_refunded_contributions(
        self, mock_exchange_rate
    ):
        """Test get_amount_raised excludes refunded USD contributions after fundraise is closed."""
        mock_exchange_rate.return_value = 0.01

        # Create USD contribution
        self._create_usd_contribution(self.fundraise, self.contributor, 10000)  # $100

        # Verify amount before refund
        amount_before = self.fundraise.get_amount_raised(currency=USD)
        self.assertEqual(amount_before, 100.0)

        # Close the fundraise (refunds all contributions)
        self.fundraise_service.close_fundraise(self.fundraise)
        self.fundraise.refresh_from_db()

        amount_after = self.fundraise.get_amount_raised(currency=USD)

        # Should be 0 after all contributions are refunded
        self.assertEqual(amount_after, 0.0)
