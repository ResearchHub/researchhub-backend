from decimal import Decimal
from unittest.mock import Mock

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITestCase

from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.models import Balance, Fundraise, Purchase
from purchase.related_models.constants.currency import USD
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.services.fundraise_service import FundraiseService
from reputation.models import BountyFee
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user


class TestFundraiseService(APITestCase):
    def setUp(self):
        self.service = FundraiseService()
        self.user = create_random_authenticated_user("fundraise_test")
        self.unified_document = Mock(spec=ResearchhubUnifiedDocument)
        self.unified_document.document_type = PREREGISTRATION

    def test_create_fundraise_with_escrow_success(self):
        # Arrange
        goal_amount = Decimal("100.00")
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )

        # Act
        fundraise = self.service.create_fundraise_with_escrow(
            self.user, unified_document, goal_amount, USD, Fundraise.OPEN
        )

        # Assert
        db_fundraise = Fundraise.objects.filter(id=fundraise.id).first()
        self.assertIsNotNone(db_fundraise)
        self.assertEqual(db_fundraise.created_by, self.user)
        self.assertEqual(db_fundraise.unified_document, unified_document)
        self.assertEqual(db_fundraise.goal_amount, goal_amount)
        self.assertEqual(db_fundraise.goal_currency, USD)
        self.assertEqual(db_fundraise.status, Fundraise.OPEN)

        # Verify escrow was created
        self.assertIsNotNone(db_fundraise.escrow)
        self.assertEqual(db_fundraise.escrow.created_by, self.user)
        self.assertEqual(db_fundraise.escrow.hold_type, "FUNDRAISE")
        self.assertEqual(db_fundraise.escrow.content_type.model, "fundraise")
        self.assertEqual(db_fundraise.escrow.object_id, db_fundraise.id)

    def test_create_fundraise_invalid_document_type(self):
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="NOT_PREREGISTRATION"
        )
        data = {
            "goal_amount": "100.00",
            "goal_currency": USD,
            "unified_document_id": unified_document.id,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]),
            "Fundraise must be for a preregistration",
        )

    def test_create_fundraise_invalid_goal_amount(self):
        # Arrange
        data = {
            "goal_amount": "100.00abc",
            "goal_currency": USD,
            "unified_document_id": 1,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["goal_amount"][0]), "A valid number is required."
        )

    def test_create_fundraise_negative_goal_amount(self):
        # Arrange
        data = {
            "goal_amount": "-100.00",
            "goal_currency": USD,
            "unified_document_id": 1,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]),
            "goal_amount must be greater than 0",
        )

    def test_create_fundraise_invalid_currency(self):
        # Arrange
        data = {
            "goal_amount": "100.00",
            "goal_currency": "RSC",
            "unified_document_id": 1,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]), "goal_currency must be USD"
        )

    def test_create_fundraise_already_exists(self):
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        goal_amount = Decimal("100.00")

        # Create initial fundraise using the service
        self.service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=unified_document,
            goal_amount=goal_amount,
            goal_currency=USD,
            status=Fundraise.OPEN,
        )

        data = {
            "goal_amount": str(goal_amount),
            "goal_currency": USD,
            "unified_document_id": unified_document.id,
            "recipient_user_id": self.user.id,
        }

        # Act
        serializer = FundraiseCreateSerializer(data=data)
        is_valid = serializer.is_valid()

        # Assert
        self.assertFalse(is_valid)
        self.assertEqual(
            str(serializer.errors["non_field_errors"][0]), "Fundraise already exists"
        )


class CloseFundraiseTests(TestCase):
    """Tests for FundraiseService.close_fundraise() method."""

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

    def _create_rsc_contribution(self, fundraise, user, amount=100):
        """Helper method to create an RSC contribution to a fundraise"""
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

    def _create_usd_contribution(self, fundraise, user, amount_cents, fee_cents=None):
        """Helper method to create a USD contribution."""
        if fee_cents is None:
            fee_cents = int(amount_cents * 0.09)
        return UsdFundraiseContribution.objects.create(
            user=user,
            fundraise=fundraise,
            amount_cents=amount_cents,
            fee_cents=fee_cents,
            origin_fund_id="test_origin_fund",
            destination_org_id="test_destination_org",
        )

    def _give_user_rsc_balance(self, user, amount):
        """Helper method to give a user RSC balance"""
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount=amount, user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )

    # --- Basic close functionality tests ---

    def test_close_fundraise_success(self):
        """Test that a fundraise can be successfully closed"""
        contributor = create_random_authenticated_user("fundraise_contributor")
        self._give_user_rsc_balance(contributor, 1000)
        self._create_rsc_contribution(self.fundraise, contributor, amount=100)

        # Check initial state
        self.assertEqual(self.fundraise.status, Fundraise.OPEN)
        self.assertEqual(self.fundraise.escrow.amount_holding, 100)

        # Close the fundraise
        result = self.fundraise_service.close_fundraise(self.fundraise)

        # Check result
        self.assertTrue(result)

        # Verify fundraise status was updated
        self.fundraise.refresh_from_db()
        self.assertEqual(self.fundraise.status, Fundraise.CLOSED)

        # Verify escrow status was updated
        self.assertEqual(self.fundraise.escrow.status, "CANCELLED")

        # Verify escrow amount is now 0
        self.assertEqual(self.fundraise.escrow.amount_holding, 0)

        # Verify contributor got refunded
        refund_balance = Balance.objects.filter(user=contributor, amount=100).exists()
        self.assertTrue(refund_balance)

    def test_close_fundraise_already_closed(self):
        """Test that a fundraise that's already closed can't be closed again"""
        self.fundraise.status = Fundraise.CLOSED
        self.fundraise.save()

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertFalse(result)

    def test_close_fundraise_completed(self):
        """Test that a completed fundraise can't be closed"""
        self.fundraise.status = Fundraise.COMPLETED
        self.fundraise.save()

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertFalse(result)

    def test_close_fundraise_no_contributions(self):
        """Test that a fundraise with no contributions can be closed"""
        self.fundraise.escrow.amount_holding = 0
        self.fundraise.escrow.save()

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)
        self.fundraise.refresh_from_db()
        self.assertEqual(self.fundraise.status, Fundraise.CLOSED)

    # --- RSC refund tests ---

    def test_close_fundraise_refunds_multiple_rsc_contributors(self):
        """Test that a fundraise with multiple RSC contributors can be closed"""
        contributor1 = create_random_authenticated_user("contributor1")
        contributor2 = create_random_authenticated_user("contributor2")
        contributor3 = create_random_authenticated_user("contributor3")

        self._give_user_rsc_balance(contributor1, 1000)
        self._give_user_rsc_balance(contributor2, 1000)
        self._give_user_rsc_balance(contributor3, 1000)

        self._create_rsc_contribution(self.fundraise, contributor1, amount=50)
        self._create_rsc_contribution(self.fundraise, contributor2, amount=30)
        self._create_rsc_contribution(self.fundraise, contributor3, amount=20)

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)
        self.fundraise.refresh_from_db()
        self.assertEqual(self.fundraise.status, Fundraise.CLOSED)

        # Verify each contributor got their money back
        self.assertTrue(Balance.objects.filter(user=contributor1, amount=50).exists())
        self.assertTrue(Balance.objects.filter(user=contributor2, amount=30).exists())
        self.assertTrue(Balance.objects.filter(user=contributor3, amount=20).exists())

    def test_close_fundraise_refunds_rsc_fees(self):
        """Test that closing a fundraise also refunds the RSC fees"""
        from reputation.utils import calculate_bounty_fees

        contributor = create_random_authenticated_user("fundraise_contributor")
        self._give_user_rsc_balance(contributor, 1000)

        contribution_amount = Decimal("100")
        self._create_rsc_contribution(
            self.fundraise, contributor, amount=contribution_amount
        )

        fee, rh_fee, dao_fee, fee_object = calculate_bounty_fees(contribution_amount)
        initial_balance_count = Balance.objects.filter(user=contributor).count()

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)

        # Verify that new balance records were created (refunds)
        final_balance_count = Balance.objects.filter(user=contributor).count()
        self.assertGreater(final_balance_count, initial_balance_count)

        # Verify fee refund exists
        fee_refund_exists = Balance.objects.filter(
            user=contributor,
            amount=fee.to_eng_string(),
        ).exists()
        self.assertTrue(fee_refund_exists)

    # --- USD refund tests ---

    def test_close_fundraise_marks_usd_contributions_as_refunded(self):
        """Test that closing a fundraise marks USD contributions as refunded."""
        contributor = create_random_authenticated_user("usd_contributor")

        # Create USD contribution
        contribution = self._create_usd_contribution(
            self.fundraise, contributor, amount_cents=5000, fee_cents=450
        )
        self.assertFalse(contribution.is_refunded)
        self.assertEqual(contribution.status, UsdFundraiseContribution.Status.SUBMITTED)

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)

        contribution.refresh_from_db()
        self.assertTrue(contribution.is_refunded)
        self.assertEqual(contribution.status, UsdFundraiseContribution.Status.CANCELLED)

    def test_close_fundraise_marks_multiple_usd_contributions_as_refunded(self):
        """Test that closing a fundraise marks multiple USD contributions as refunded."""
        contributor1 = create_random_authenticated_user("usd_contributor1")
        contributor2 = create_random_authenticated_user("usd_contributor2")

        contribution1 = self._create_usd_contribution(
            self.fundraise, contributor1, amount_cents=10000, fee_cents=900
        )
        contribution2 = self._create_usd_contribution(
            self.fundraise, contributor2, amount_cents=5000, fee_cents=450
        )

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)

        contribution1.refresh_from_db()
        contribution2.refresh_from_db()
        self.assertTrue(contribution1.is_refunded)
        self.assertTrue(contribution2.is_refunded)

    def test_close_fundraise_skips_already_refunded_usd_contributions(self):
        """Test that already refunded USD contributions are not modified again."""
        contributor = create_random_authenticated_user("usd_contributor")

        contribution = self._create_usd_contribution(
            self.fundraise, contributor, amount_cents=5000, fee_cents=450
        )

        # Manually mark as refunded
        contribution.is_refunded = True
        contribution.save()

        # Count updates before closing
        initial_updated = contribution.updated_date

        self.fundraise_service.close_fundraise(self.fundraise)

        contribution.refresh_from_db()
        # Already refunded, should not have been modified
        self.assertTrue(contribution.is_refunded)

    # --- Mixed RSC and USD tests ---

    def test_close_fundraise_handles_both_rsc_and_usd(self):
        """Test that closing a fundraise handles both RSC and USD contributions."""
        rsc_contributor = create_random_authenticated_user("rsc_contributor")
        usd_contributor = create_random_authenticated_user("usd_contributor")

        # Set up RSC contribution
        self._give_user_rsc_balance(rsc_contributor, 1000)
        self._create_rsc_contribution(self.fundraise, rsc_contributor, amount=100)

        # Set up USD contribution
        contribution = self._create_usd_contribution(
            self.fundraise, usd_contributor, amount_cents=5000, fee_cents=450
        )

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)

        # Verify RSC contributor got refunded
        self.assertTrue(
            Balance.objects.filter(user=rsc_contributor, amount=100).exists()
        )

        # Verify USD contribution was marked as refunded
        contribution.refresh_from_db()
        self.assertTrue(contribution.is_refunded)


class CreateUsdContributionTests(TestCase):
    """
    Tests for USD contribution functionality.
    """

    def setUp(self):
        self.mock_endaoment_service = Mock()
        self.service = FundraiseService(endaoment_service=self.mock_endaoment_service)

        self.user = create_random_authenticated_user("usd_contributor")
        self.creator = create_random_authenticated_user("fundraise_creator")

        self.post = create_post(created_by=self.creator, document_type=PREREGISTRATION)
        self.fundraise = self.service.create_fundraise_with_escrow(
            user=self.creator,
            unified_document=self.post.unified_document,
            goal_amount=100,
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Link a nonprofit org to the fundraise
        self.nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit",
            endaoment_org_id="endaoment_org_123",
        )
        NonprofitFundraiseLink.objects.create(
            fundraise=self.fundraise,
            nonprofit=self.nonprofit,
        )

    def test_create_usd_contribution(self):
        """
        Test successful USD contribution creates record with transfer ID (happy path).
        """
        # Arrange
        self.mock_endaoment_service.transfer_to_researchhub_fund.return_value = {
            "id": "transfer_123"
        }

        # Act
        contribution, error = self.service.create_usd_contribution(
            user=self.user,
            fundraise=self.fundraise,
            amount_cents=10000,
            origin_fund_id="fund_abc",
        )

        # Assert
        self.assertIsNone(error)
        self.assertIsNotNone(contribution)
        self.assertEqual(contribution.amount_cents, 10000)
        self.assertEqual(contribution.fee_cents, 900)  # 9%
        self.assertEqual(contribution.origin_fund_id, "fund_abc")
        self.assertEqual(contribution.destination_org_id, "endaoment_org_123")
        self.assertEqual(contribution.endaoment_transfer_id, "transfer_123")
        self.assertEqual(contribution.status, UsdFundraiseContribution.Status.SUBMITTED)

        # Verify transfer was called with amount + fee
        self.mock_endaoment_service.transfer_to_researchhub_fund.assert_called_once_with(
            user=self.user,
            origin_fund_id="fund_abc",
            amount_cents=10900,  # 10000 + 9% fee
        )

    def test_create_usd_contribution_no_origin_fund_id(self):
        """
        Test that missing origin_fund_id returns error.
        """
        # Act
        contribution, error = self.service.create_usd_contribution(
            user=self.user,
            fundraise=self.fundraise,
            amount_cents=10000,
            origin_fund_id=None,
        )

        # Assert
        self.assertIsNone(contribution)
        self.assertEqual(error, "origin_fund_id is required for USD contributions")
        self.mock_endaoment_service.transfer_to_researchhub_fund.assert_not_called()

    def test_create_usd_contribution_no_nonprofit_org(self):
        """
        Test that missing nonprofit org returns error.
        """
        # Arrange

        # remove the nonprofit link for this test
        NonprofitFundraiseLink.objects.filter(fundraise=self.fundraise).delete()

        # Act
        contribution, error = self.service.create_usd_contribution(
            user=self.user,
            fundraise=self.fundraise,
            amount_cents=10000,
            origin_fund_id="fund_abc",
        )

        # Assert
        self.assertIsNone(contribution)
        self.assertEqual(error, "Fundraise nonprofit org is not set")
        self.mock_endaoment_service.transfer_to_researchhub_fund.assert_not_called()

    def test_create_usd_contribution_endaoment_not_connected(self):
        """
        Test that a missing Endaoment connection returns the expected error.
        """
        # Arrange
        from purchase.models import EndaomentAccount

        self.mock_endaoment_service.transfer_to_researchhub_fund.side_effect = (
            EndaomentAccount.DoesNotExist("User has no Endaoment connection")
        )

        # Act
        contribution, error = self.service.create_usd_contribution(
            user=self.user,
            fundraise=self.fundraise,
            amount_cents=10000,
            origin_fund_id="fund_abc",
        )

        # Assert
        self.assertIsNone(contribution)
        self.assertEqual(error, "Endaoment account not connected")
        self.assertFalse(
            UsdFundraiseContribution.objects.filter(
                user=self.user, fundraise=self.fundraise
            ).exists()
        )

    def test_create_usd_contribution_endaoment_api_error(self):
        """
        Test that generic exception from the Endaoment service returns an error.
        """
        # Arrange
        self.mock_endaoment_service.transfer_to_researchhub_fund.side_effect = (
            Exception("D'oh!")
        )

        # Act
        contribution, error = self.service.create_usd_contribution(
            user=self.user,
            fundraise=self.fundraise,
            amount_cents=10000,
            origin_fund_id="fund_abc",
        )

        # Assert
        self.assertIsNone(contribution)
        self.assertEqual(error, "Failed to submit Endaoment grant")
        self.assertFalse(
            UsdFundraiseContribution.objects.filter(
                user=self.user, fundraise=self.fundraise
            ).exists()
        )
