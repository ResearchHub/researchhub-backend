from decimal import Decimal
from unittest.mock import Mock

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APITestCase

from purchase.models import Balance, Fundraise, Purchase
from purchase.related_models.constants.currency import USD
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from purchase.serializers.fundraise_create_serializer import FundraiseCreateSerializer
from purchase.services.fundraise_service import FundraiseService
from organizations.models import NonprofitFundraiseLink, NonprofitOrg
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

    def test_get_funder_overview_returns_dict(self):
        # Act
        result = self.service.get_funder_overview(self.user)

        # Assert
        self.assertIsInstance(result, dict)

    def test_get_grant_overview_returns_dict(self):
        # Act
        result = self.service.get_grant_overview(self.user, 1)

        # Assert
        self.assertIsInstance(result, dict)

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

    def test_create_endaoment_reservation_requires_nonprofit_link(self):
        # Arrange
        fundraise = self.service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type=PREREGISTRATION
            ),
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )

        # Act
        contribution, error = self.service.create_endaoment_reservation(
            user=self.user,
            fundraise=fundraise,
            amount_cents=10000,
            origin_fund_id="fund-1",
        )

        # Assert
        self.assertIsNone(contribution)
        self.assertEqual(error, "Fundraise is not linked to an Endaoment nonprofit")

    def test_create_endaoment_reservation_success(self):
        # Arrange
        fundraise = self.service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type=PREREGISTRATION
            ),
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )
        nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit", endaoment_org_id="org-123"
        )
        NonprofitFundraiseLink.objects.create(
            nonprofit=nonprofit, fundraise=fundraise
        )

        # Act
        contribution, error = self.service.create_endaoment_reservation(
            user=self.user,
            fundraise=fundraise,
            amount_cents=15000,
            origin_fund_id="fund-123",
        )

        # Assert
        self.assertIsNone(error)
        self.assertIsNotNone(contribution)
        self.assertEqual(
            contribution.source, UsdFundraiseContribution.Source.ENDAOMENT
        )
        self.assertEqual(
            contribution.status, UsdFundraiseContribution.Status.RESERVED
        )
        self.assertEqual(contribution.origin_fund_id, "fund-123")
        self.assertEqual(contribution.destination_org_id, "org-123")

    def test_submit_endaoment_grants_updates_status(self):
        # Arrange
        fundraise = self.service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type=PREREGISTRATION
            ),
            goal_amount=Decimal("100.00"),
            goal_currency=USD,
            status=Fundraise.OPEN,
        )
        reservation = UsdFundraiseContribution.objects.create(
            user=self.user,
            fundraise=fundraise,
            amount_cents=10000,
            fee_cents=0,
            source=UsdFundraiseContribution.Source.ENDAOMENT,
            status=UsdFundraiseContribution.Status.RESERVED,
            origin_fund_id="fund-1",
            destination_org_id="org-1",
        )

        mock_endaoment = Mock()
        mock_endaoment.create_grant.return_value = {"id": "transfer-1"}
        service = FundraiseService(endaoment_service=mock_endaoment)

        # Act
        service.submit_endaoment_grants(fundraise)

        # Assert
        reservation.refresh_from_db()
        self.assertEqual(
            reservation.status, UsdFundraiseContribution.Status.SUBMITTED
        )
        self.assertEqual(reservation.endaoment_transfer_id, "transfer-1")
        mock_endaoment.create_grant.assert_called_once()


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
        )

    def _give_user_rsc_balance(self, user, amount):
        """Helper method to give a user RSC balance"""
        DISTRIBUTION_CONTENT_TYPE = ContentType.objects.get(model="distribution")
        Balance.objects.create(
            amount=amount, user=user, content_type=DISTRIBUTION_CONTENT_TYPE
        )

    def _give_user_usd_balance(self, user, amount_cents):
        """Helper method to give a user USD balance."""
        from purchase.related_models.usd_balance_model import UsdBalance

        UsdBalance.objects.create(user=user, amount_cents=amount_cents)

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

    def test_close_fundraise_refunds_usd_contributions(self):
        """Test that closing a fundraise refunds USD contributions."""
        contributor = create_random_authenticated_user("usd_contributor")
        self._give_user_usd_balance(contributor, 10000)  # $100
        initial_balance = contributor.get_usd_balance_cents()

        # Create USD contribution: $50 + $4.50 fee = $54.50 total
        contribution = self._create_usd_contribution(
            self.fundraise, contributor, amount_cents=5000, fee_cents=450
        )
        self.assertFalse(contribution.is_refunded)

        # Simulate the deduction that would have happened when contributing
        contributor.decrease_usd_balance(5450, source=contribution)
        self.assertEqual(contributor.get_usd_balance_cents(), 10000 - 5450)

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)
        self.assertEqual(contributor.get_usd_balance_cents(), initial_balance)

        contribution.refresh_from_db()
        self.assertTrue(contribution.is_refunded)

    def test_close_fundraise_refunds_multiple_usd_contributors(self):
        """Test that closing a fundraise refunds multiple USD contributors."""
        contributor1 = create_random_authenticated_user("usd_contributor1")
        contributor2 = create_random_authenticated_user("usd_contributor2")

        self._give_user_usd_balance(contributor1, 20000)
        self._give_user_usd_balance(contributor2, 15000)

        initial_balance1 = contributor1.get_usd_balance_cents()
        initial_balance2 = contributor2.get_usd_balance_cents()

        contribution1 = self._create_usd_contribution(
            self.fundraise, contributor1, amount_cents=10000, fee_cents=900
        )
        contribution2 = self._create_usd_contribution(
            self.fundraise, contributor2, amount_cents=5000, fee_cents=450
        )

        contributor1.decrease_usd_balance(10900, source=contribution1)
        contributor2.decrease_usd_balance(5450, source=contribution2)

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)
        self.assertEqual(contributor1.get_usd_balance_cents(), initial_balance1)
        self.assertEqual(contributor2.get_usd_balance_cents(), initial_balance2)

    def test_close_fundraise_skips_already_refunded_usd_contributions(self):
        """Test that already refunded USD contributions are not refunded again."""
        contributor = create_random_authenticated_user("usd_contributor")
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

        self.fundraise_service.close_fundraise(self.fundraise)

        # Verify balance hasn't changed (no double refund)
        self.assertEqual(
            contributor.get_usd_balance_cents(), balance_after_manual_refund
        )

    # --- Mixed RSC and USD tests ---

    def test_close_fundraise_refunds_both_rsc_and_usd(self):
        """Test that closing a fundraise refunds both RSC and USD contributions."""
        rsc_contributor = create_random_authenticated_user("rsc_contributor")
        usd_contributor = create_random_authenticated_user("usd_contributor")

        # Set up RSC contribution
        self._give_user_rsc_balance(rsc_contributor, 1000)
        self._create_rsc_contribution(self.fundraise, rsc_contributor, amount=100)

        # Set up USD contribution
        self._give_user_usd_balance(usd_contributor, 10000)
        initial_usd_balance = usd_contributor.get_usd_balance_cents()
        contribution = self._create_usd_contribution(
            self.fundraise, usd_contributor, amount_cents=5000, fee_cents=450
        )
        usd_contributor.decrease_usd_balance(5450, source=contribution)

        result = self.fundraise_service.close_fundraise(self.fundraise)

        self.assertTrue(result)

        # Verify RSC contributor got refunded
        self.assertTrue(
            Balance.objects.filter(user=rsc_contributor, amount=100).exists()
        )

        # Verify USD contributor got refunded
        self.assertEqual(usd_contributor.get_usd_balance_cents(), initial_usd_balance)
