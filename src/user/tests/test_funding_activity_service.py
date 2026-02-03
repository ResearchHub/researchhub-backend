"""
Tests for FundingActivityService: query methods and create_funding_activity.
"""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import Purchase, UsdFundraiseContribution
from purchase.related_models.balance_model import Balance
from purchase.related_models.fundraise_model import Fundraise
from reputation.models import Distribution
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.management.commands.setup_bank_user import BANK_EMAIL
from user.related_models.funding_activity_model import FundingActivity
from user.related_models.user_model import FOUNDATION_EMAIL
from user.services.funding_activity_service import FundingActivityService
from user.tests.helpers import create_user


class FundingActivityServiceTests(TestCase):
    def setUp(self):
        self.user = create_user(email="funder@test.com")
        self.other_user = create_user(email="recipient@test.com")

    def test_get_fundraise_payouts_returns_only_completed(self):
        """get_fundraise_payouts returns Purchases where fundraise escrow is PAID."""
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise_paid = Fundraise.objects.create(
            created_by=self.other_user,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        escrow_paid = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.user,
            content_type=ct_fundraise,
            object_id=fundraise_paid.id,
        )
        fundraise_paid.escrow = escrow_paid
        fundraise_paid.save()
        purchase_paid = Purchase.objects.create(
            user=self.user,
            content_type=ct_fundraise,
            object_id=fundraise_paid.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="100",
            purchase_method=Purchase.OFF_CHAIN,
        )
        qs = FundingActivityService.get_fundraise_payouts()
        self.assertIn(purchase_paid, qs)

    def test_multiple_fundraises_only_completed_in_funding_activity(self):
        """Multiple fundraises: only the completed one (escrow PAID) is in funding activity."""
        uni_doc_completed = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        uni_doc_in_progress = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)

        # Completed fundraise (escrow PAID)
        fundraise_completed = Fundraise.objects.create(
            created_by=self.other_user,
            status=Fundraise.CLOSED,
            unified_document=uni_doc_completed,
        )
        escrow_paid = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.user,
            content_type=ct_fundraise,
            object_id=fundraise_completed.id,
        )
        fundraise_completed.escrow = escrow_paid
        fundraise_completed.save()
        purchase_completed = Purchase.objects.create(
            user=self.user,
            content_type=ct_fundraise,
            object_id=fundraise_completed.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="100",
            purchase_method=Purchase.OFF_CHAIN,
        )

        # In-progress fundraise (escrow PENDING)
        fundraise_in_progress = Fundraise.objects.create(
            created_by=self.other_user,
            status=Fundraise.OPEN,
            unified_document=uni_doc_in_progress,
        )
        escrow_pending = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PENDING,
            created_by=self.user,
            content_type=ct_fundraise,
            object_id=fundraise_in_progress.id,
        )
        fundraise_in_progress.escrow = escrow_pending
        fundraise_in_progress.save()
        purchase_in_progress = Purchase.objects.create(
            user=self.user,
            content_type=ct_fundraise,
            object_id=fundraise_in_progress.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="50",
            purchase_method=Purchase.OFF_CHAIN,
        )

        # get_fundraise_payouts returns only the completed one
        qs = FundingActivityService.get_fundraise_payouts()
        self.assertIn(purchase_completed, qs)
        self.assertNotIn(purchase_in_progress, qs)
        self.assertEqual(qs.count(), 1)

        # create_funding_activity for completed creates activity; for in-progress returns None
        with patch.object(Fundraise, "get_recipient", return_value=self.other_user):
            activity_completed = FundingActivityService.create_funding_activity(
                FundingActivity.FUNDRAISE_PAYOUT, purchase_completed
            )
        activity_in_progress = FundingActivityService.create_funding_activity(
            FundingActivity.FUNDRAISE_PAYOUT, purchase_in_progress
        )
        self.assertIsNotNone(activity_completed)
        self.assertIsNone(activity_in_progress)
        self.assertEqual(FundingActivity.objects.count(), 1)
        self.assertEqual(
            FundingActivity.objects.get().source_object_id,
            purchase_completed.id,
        )

    def test_create_funding_activity_idempotent(self):
        """create_funding_activity returns existing when same source already exists."""
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.other_user,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.user,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=ct_fundraise,
            object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="100",
            purchase_method=Purchase.OFF_CHAIN,
        )
        with patch.object(Fundraise, "get_recipient", return_value=self.other_user):
            first = FundingActivityService.create_funding_activity(
                FundingActivity.FUNDRAISE_PAYOUT, purchase
            )
            second = FundingActivityService.create_funding_activity(
                FundingActivity.FUNDRAISE_PAYOUT, purchase
            )
        self.assertIsNotNone(first)
        self.assertEqual(first.id, second.id)
        self.assertEqual(FundingActivity.objects.count(), 1)

    def test_create_fundraise_payout_creates_activity_and_recipient(self):
        """FUNDRAISE_PAYOUT creates FundingActivity + one Recipient."""
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.other_user,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.user,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=ct_fundraise,
            object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="100",
            purchase_method=Purchase.OFF_CHAIN,
        )
        with patch.object(Fundraise, "get_recipient", return_value=self.other_user):
            activity = FundingActivityService.create_funding_activity(
                FundingActivity.FUNDRAISE_PAYOUT, purchase
            )
        self.assertIsNotNone(activity)
        self.assertEqual(activity.source_type, FundingActivity.FUNDRAISE_PAYOUT)
        self.assertEqual(activity.total_amount, Decimal("100"))
        self.assertEqual(activity.funder_id, self.user.id)
        recipients = list(activity.recipients.all())
        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0].recipient_user_id, self.other_user.id)
        self.assertEqual(recipients[0].amount, Decimal("100"))

    def test_fundraise_payout_total_amount_full_when_user_used_locked_and_regular(
        self,
    ):
        """
        User has 50 available + 50 locked (50-50 balance). They fund 100.
        FundingActivity must record total_amount=100 (100% of contribution).
        """
        ct_balance = ContentType.objects.get_for_model(Purchase)
        Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=ct_balance,
            is_locked=False,
        )
        Balance.objects.create(
            user=self.user,
            amount="50",
            content_type=ct_balance,
            is_locked=True,
            lock_type=Balance.LockType.REFERRAL_BONUS,
        )
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.other_user,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.user,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=ct_fundraise,
            object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="100",
            purchase_method=Purchase.OFF_CHAIN,
        )
        with patch.object(Fundraise, "get_recipient", return_value=self.other_user):
            activity = FundingActivityService.create_funding_activity(
                FundingActivity.FUNDRAISE_PAYOUT, purchase
            )
        self.assertIsNotNone(activity)
        self.assertEqual(
            activity.total_amount,
            Decimal("100"),
            "Full 100% of contribution must be recorded as total_amount",
        )
        self.assertEqual(activity.recipients.count(), 1)
        self.assertEqual(
            activity.recipients.first().amount,
            Decimal("100"),
            "Recipient amount must be full 100",
        )

    def test_create_fundraise_payout_usd_creates_activity_and_recipient(self):
        """FUNDRAISE_PAYOUT_USD creates FundingActivity + one Recipient from UsdFundraiseContribution."""
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.other_user,
            status=Fundraise.COMPLETED,
            unified_document=uni_doc,
        )
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.user,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        contribution = UsdFundraiseContribution.objects.create(
            user=self.user,
            fundraise=fundraise,
            amount_cents=10000,
            fee_cents=900,
            amount_rsc=Decimal("1000"),
            is_refunded=False,
        )
        with patch.object(Fundraise, "get_recipient", return_value=self.other_user):
            activity = FundingActivityService.create_funding_activity(
                FundingActivity.FUNDRAISE_PAYOUT_USD, contribution
            )
        self.assertIsNotNone(activity)
        self.assertEqual(activity.source_type, FundingActivity.FUNDRAISE_PAYOUT_USD)
        self.assertEqual(activity.total_amount, Decimal("1000"))
        self.assertEqual(activity.funder_id, self.user.id)
        recipients = list(activity.recipients.all())
        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0].recipient_user_id, self.other_user.id)
        self.assertEqual(recipients[0].amount, Decimal("1000"))

    def test_create_fee_creates_activity_no_recipient(self):
        """FEE creates FundingActivity, no recipient."""
        dist = Distribution.objects.create(
            giver=self.user,
            recipient=None,
            amount=Decimal("10"),
            distribution_type="BOUNTY_RH_FEE",
        )
        activity = FundingActivityService.create_funding_activity(
            FundingActivity.FEE, dist
        )
        self.assertIsNotNone(activity)
        self.assertEqual(activity.source_type, FundingActivity.FEE)
        self.assertEqual(activity.total_amount, Decimal("10"))
        self.assertEqual(activity.funder_id, self.user.id)
        self.assertEqual(activity.recipients.count(), 0)

    def test_get_fees_returns_fee_distributions(self):
        """get_fees returns Distribution with fee types."""
        Distribution.objects.create(
            giver=self.user,
            amount=Decimal("5"),
            distribution_type="BOUNTY_RH_FEE",
        )
        qs = FundingActivityService.get_fees()
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().distribution_type, "BOUNTY_RH_FEE")

    def test_create_funding_activity_stored_when_funder_is_bank(self):
        """We store FundingActivity when the funder is bank (activity is tracked)."""
        bank_user = create_user(email=BANK_EMAIL)
        dist = Distribution.objects.create(
            giver=bank_user,
            recipient=None,
            amount=Decimal("10"),
            distribution_type="BOUNTY_RH_FEE",
        )
        activity = FundingActivityService.create_funding_activity(
            FundingActivity.FEE, dist
        )
        self.assertIsNotNone(activity)
        self.assertEqual(activity.funder_id, bank_user.id)
        self.assertEqual(FundingActivity.objects.filter(funder=bank_user).count(), 1)

    def test_create_funding_activity_stored_when_funder_is_foundation(self):
        """We store FundingActivity when the funder is foundation (activity is tracked)."""
        foundation_user = create_user(email=FOUNDATION_EMAIL)
        dist = Distribution.objects.create(
            giver=foundation_user,
            recipient=None,
            amount=Decimal("10"),
            distribution_type="BOUNTY_RH_FEE",
        )
        activity = FundingActivityService.create_funding_activity(
            FundingActivity.FEE, dist
        )
        self.assertIsNotNone(activity)
        self.assertEqual(activity.funder_id, foundation_user.id)
