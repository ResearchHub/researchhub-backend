from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.models import Fundraise
from reputation.models import Escrow
from researchhub.settings import ENDAOMENT_ACCOUNT_ID
from researchhub_document.related_models.constants.document_type import PAPER
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


class FundraiseRecipientTest(TestCase):
    def setUp(self):
        """Set up test data"""
        self.User = get_user_model()

        # Create users
        self.creator = self.User.objects.create(
            username="creator", email="creator@example.com"
        )

        # Create endaoment user with ID from settings
        self.endaoment_user = self.User.objects.create(
            id=int(ENDAOMENT_ACCOUNT_ID),
            username="endaoment",
            email="endaoment@example.com",
        )

        # Create document
        self.document = ResearchhubUnifiedDocument.objects.create(document_type=PAPER)

        # Create fundraise
        self.fundraise = Fundraise.objects.create(
            created_by=self.creator,
            unified_document=self.document,
            goal_amount=Decimal("100.0"),
            goal_currency="USD",
        )

        # Create escrow
        self.escrow = Escrow.objects.create(
            created_by=self.creator,
            hold_type=Escrow.FUNDRAISE,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=self.fundraise.id,
            amount_holding=Decimal("50.0"),
        )
        self.fundraise.escrow = self.escrow
        self.fundraise.save()

        # Create nonprofit
        self.nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit", endaoment_org_id="12345"
        )

    def test_get_recipient_no_nonprofit(self):
        """Test that fundraise without nonprofit link returns creator as recipient"""
        recipient = self.fundraise.get_recipient()
        self.assertEqual(recipient, self.creator)

    def test_get_recipient_with_nonprofit(self):
        """Test fundraise with nonprofit link returns Endaoment account"""
        # Create nonprofit link
        NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit, fundraise=self.fundraise
        )

        recipient = self.fundraise.get_recipient()
        self.assertEqual(recipient, self.endaoment_user)
        self.assertEqual(recipient.id, int(ENDAOMENT_ACCOUNT_ID))

    @override_settings(ENDAOMENT_ACCOUNT_ID=None)
    def test_get_recipient_with_nonprofit_no_endaoment_id(self):
        """Test error when nonprofit link exists without ENDAOMENT_ACCOUNT_ID"""
        # Create nonprofit link
        NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit, fundraise=self.fundraise
        )

        # Verify that calling get_recipient raises a ValueError
        with self.assertRaises(ValueError) as context:
            self.fundraise.get_recipient()

        # Check the error message
        error_msg = str(context.exception)
        self.assertIn("Fundraise is linked to a nonprofit but", error_msg)
        self.assertIn("ENDAOMENT_ACCOUNT_ID is not configured", error_msg)

    def test_payout_funds_correct_recipient(self):
        """Test that payout is sent to correct recipient based on nonprofit link"""
        # Create a mock version of escrow.payout to capture the recipient
        original_payout = self.escrow.payout

        payout_called = False
        payout_recipient = None

        def mock_payout(recipient, payout_amount):
            nonlocal payout_called, payout_recipient
            payout_called = True
            payout_recipient = recipient
            return True

        # Replace with mock
        self.escrow.payout = mock_payout

        try:
            # Test without nonprofit link
            result = self.fundraise.payout_funds()
            self.assertTrue(result)
            self.assertTrue(payout_called)
            self.assertEqual(payout_recipient, self.creator)

            # Reset mock
            payout_called = False
            payout_recipient = None

            # Create nonprofit link and test again
            NonprofitFundraiseLink.objects.create(
                nonprofit=self.nonprofit, fundraise=self.fundraise
            )

            result = self.fundraise.payout_funds()
            self.assertTrue(result)
            self.assertTrue(payout_called)
            self.assertEqual(payout_recipient, self.endaoment_user)
            self.assertEqual(payout_recipient.id, int(ENDAOMENT_ACCOUNT_ID))

        finally:
            # Restore original method
            self.escrow.payout = original_payout
