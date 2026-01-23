from decimal import Decimal

from rest_framework.test import APITestCase

from purchase.models import Fundraise, FundingCredit
from purchase.services.funding_credit_service import FundingCreditService
from purchase.services.fundraise_service import FundraiseService
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user


class TestFundingCreditService(APITestCase):
    def setUp(self):
        self.service = FundingCreditService()
        self.user = create_random_authenticated_user("credit_test")

    def test_get_user_balance_empty(self):
        """Test balance for user with no credits."""
        balance = self.service.get_user_balance(self.user)
        self.assertEqual(balance, Decimal("0"))

    def test_add_credits_success(self):
        """Test adding credits to a user."""
        credit = self.service.add_credits(self.user, Decimal("100"))

        self.assertIsNotNone(credit)
        self.assertEqual(credit.amount, Decimal("100"))
        self.assertEqual(credit.credit_type, FundingCredit.CreditType.STAKING_REWARD)
        self.assertEqual(credit.user, self.user)

    def test_add_credits_invalid_amount(self):
        """Test that adding zero or negative credits raises error."""
        with self.assertRaises(ValueError):
            self.service.add_credits(self.user, Decimal("0"))

        with self.assertRaises(ValueError):
            self.service.add_credits(self.user, Decimal("-100"))

    def test_add_credits_with_source(self):
        """Test adding credits with a source object."""
        # Use user as source for simplicity
        credit = self.service.add_credits(
            self.user, Decimal("100"), source=self.user
        )

        self.assertIsNotNone(credit.content_type)
        self.assertEqual(credit.object_id, self.user.id)

    def test_get_user_balance_with_credits(self):
        """Test balance calculation with multiple credits."""
        self.service.add_credits(self.user, Decimal("100"))
        self.service.add_credits(self.user, Decimal("50"))

        balance = self.service.get_user_balance(self.user)
        self.assertEqual(balance, Decimal("150"))

    def test_spend_credits_success(self):
        """Test spending credits on a fundraise."""
        # Add credits first
        self.service.add_credits(self.user, Decimal("100"))

        # Create a fundraise
        fundraise_service = FundraiseService()
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        fundraise = fundraise_service.create_fundraise_with_escrow(
            self.user, unified_document, Decimal("1000")
        )

        # Spend credits
        credit, error = self.service.spend_credits(
            self.user, Decimal("50"), fundraise
        )

        self.assertIsNone(error)
        self.assertIsNotNone(credit)
        self.assertEqual(credit.amount, Decimal("-50"))
        self.assertEqual(
            credit.credit_type, FundingCredit.CreditType.FUNDRAISE_CONTRIBUTION
        )

        # Check remaining balance
        balance = self.service.get_user_balance(self.user)
        self.assertEqual(balance, Decimal("50"))

    def test_spend_credits_insufficient_balance(self):
        """Test spending more credits than available."""
        self.service.add_credits(self.user, Decimal("50"))

        # Create a fundraise
        fundraise_service = FundraiseService()
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        fundraise = fundraise_service.create_fundraise_with_escrow(
            self.user, unified_document, Decimal("1000")
        )

        # Try to spend more than available
        credit, error = self.service.spend_credits(
            self.user, Decimal("100"), fundraise
        )

        self.assertIsNone(credit)
        self.assertEqual(error, "Insufficient funding credit balance")

        # Balance should be unchanged
        balance = self.service.get_user_balance(self.user)
        self.assertEqual(balance, Decimal("50"))

    def test_spend_credits_invalid_amount(self):
        """Test that spending zero or negative credits returns error."""
        # Create a fundraise
        fundraise_service = FundraiseService()
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        fundraise = fundraise_service.create_fundraise_with_escrow(
            self.user, unified_document, Decimal("1000")
        )

        credit, error = self.service.spend_credits(
            self.user, Decimal("0"), fundraise
        )
        self.assertEqual(error, "Amount must be positive")

        credit, error = self.service.spend_credits(
            self.user, Decimal("-50"), fundraise
        )
        self.assertEqual(error, "Amount must be positive")

    def test_get_recent_transactions(self):
        """Test getting recent transactions."""
        # Add several credits
        for i in range(5):
            self.service.add_credits(self.user, Decimal(str((i + 1) * 10)))

        transactions = self.service.get_recent_transactions(self.user, limit=3)

        self.assertEqual(len(transactions), 3)
        # Should be ordered by created_date descending (newest first)
        self.assertEqual(transactions[0].amount, Decimal("50"))
        self.assertEqual(transactions[1].amount, Decimal("40"))
        self.assertEqual(transactions[2].amount, Decimal("30"))

    def test_balance_after_multiple_operations(self):
        """Test balance after multiple add and spend operations."""
        # Add credits
        self.service.add_credits(self.user, Decimal("100"))
        self.service.add_credits(self.user, Decimal("200"))

        # Create fundraise and spend
        fundraise_service = FundraiseService()
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        fundraise = fundraise_service.create_fundraise_with_escrow(
            self.user, unified_document, Decimal("1000")
        )

        self.service.spend_credits(self.user, Decimal("150"), fundraise)

        # Add more credits
        self.service.add_credits(self.user, Decimal("50"))

        # Final balance: 100 + 200 - 150 + 50 = 200
        balance = self.service.get_user_balance(self.user)
        self.assertEqual(balance, Decimal("200"))


class TestUserFundingCreditMethods(APITestCase):
    """Test the User model helper methods for funding credits."""

    def setUp(self):
        self.user = create_random_authenticated_user("user_credit_test")

    def test_get_funding_credit_balance(self):
        """Test User.get_funding_credit_balance()."""
        FundingCredit.objects.create(
            user=self.user,
            amount=Decimal("100"),
            credit_type=FundingCredit.CreditType.STAKING_REWARD,
        )

        balance = self.user.get_funding_credit_balance()
        self.assertEqual(balance, Decimal("100"))

    def test_increase_funding_credits(self):
        """Test User.increase_funding_credits()."""
        credit = self.user.increase_funding_credits(Decimal("75"))

        self.assertEqual(credit.amount, Decimal("75"))
        self.assertEqual(self.user.get_funding_credit_balance(), Decimal("75"))

    def test_increase_funding_credits_invalid(self):
        """Test that increasing by zero or negative raises error."""
        with self.assertRaises(ValueError):
            self.user.increase_funding_credits(Decimal("0"))

        with self.assertRaises(ValueError):
            self.user.increase_funding_credits(Decimal("-50"))

    def test_decrease_funding_credits(self):
        """Test User.decrease_funding_credits()."""
        self.user.increase_funding_credits(Decimal("100"))

        credit = self.user.decrease_funding_credits(Decimal("30"))

        self.assertEqual(credit.amount, Decimal("-30"))
        self.assertEqual(self.user.get_funding_credit_balance(), Decimal("70"))

    def test_decrease_funding_credits_insufficient(self):
        """Test that decreasing more than balance raises error."""
        self.user.increase_funding_credits(Decimal("50"))

        with self.assertRaises(ValueError) as context:
            self.user.decrease_funding_credits(Decimal("100"))

        self.assertEqual(
            str(context.exception), "Insufficient funding credit balance"
        )
