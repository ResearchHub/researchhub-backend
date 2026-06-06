"""
Tests for backfill_funding_activity_amounts management command.
"""

from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from purchase.models import Purchase
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.tests.helpers import create_user


class BackfillFundingActivityAmountsTests(TestCase):
    def setUp(self):
        self.funder = create_user(email="backfill-funder@test.com")
        self.recipient = create_user(email="backfill-recipient@test.com")

    def _call(self, *args, **kwargs):
        out = StringIO()
        call_command("backfill_funding_activity_amounts", *args, stdout=out, **kwargs)
        return out.getvalue()

    def _create_fundraise_purchase_activity(
        self, purchase, unified_document, usd_cents=0
    ):
        """Simulate a pre-PR2 FundingActivity row with no usd_cents."""
        ct_purchase = ContentType.objects.get_for_model(Purchase)
        activity = FundingActivity.objects.create(
            funder=self.funder,
            source_type=FundingActivity.FUNDRAISE_PAYOUT,
            total_amount=Decimal(str(purchase.amount)),
            usd_cents=usd_cents,
            unified_document=unified_document,
            activity_date=purchase.created_date,
            source_content_type=ct_purchase,
            source_object_id=purchase.pk,
        )
        FundingActivityRecipient.objects.create(
            activity=activity,
            recipient_user=self.recipient,
            amount=Decimal(str(purchase.amount)),
            usd_cents=usd_cents,
        )
        return activity

    def _create_completed_fundraise_purchase(self, amount="100", rsc_usd_rate=None):
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.recipient,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.funder,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        purchase = Purchase.objects.create(
            user=self.funder,
            content_type=ct_fundraise,
            object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount=amount,
            purchase_method=Purchase.OFF_CHAIN,
            rsc_usd_rate=rsc_usd_rate,
        )
        return purchase, fundraise

    def test_populates_usd_cents_from_purchase_rate(self):
        """Populates usd_cents on RSC-origin row when Purchase has rsc_usd_rate."""
        # Arrange
        purchase, fundraise = self._create_completed_fundraise_purchase(
            amount="100", rsc_usd_rate=0.5
        )
        activity = self._create_fundraise_purchase_activity(
            purchase, fundraise.unified_document
        )

        # Act
        self._call()

        # Assert
        activity.refresh_from_db()
        recipient = activity.recipients.get()
        self.assertEqual(activity.usd_cents, 5000)
        self.assertEqual(recipient.usd_cents, 5000)
        self.assertEqual(activity.total_amount, Decimal("100"))

    def test_falls_back_to_historical_rate_when_purchase_rate_null(self):
        """Falls back to historical rate when Purchase.rsc_usd_rate is null."""
        # Arrange
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, target_currency="USD")
        purchase, fundraise = self._create_completed_fundraise_purchase(
            amount="100", rsc_usd_rate=None
        )
        activity = self._create_fundraise_purchase_activity(
            purchase, fundraise.unified_document
        )

        # Act
        self._call()

        # Assert
        activity.refresh_from_db()
        self.assertEqual(activity.usd_cents, 5000)
        self.assertEqual(activity.recipients.get().usd_cents, 5000)

    def test_skips_rows_already_populated(self):
        """Skips rows that already have usd_cents > 0 (idempotent)."""
        # Arrange
        purchase, fundraise = self._create_completed_fundraise_purchase(
            amount="100", rsc_usd_rate=0.5
        )
        activity = self._create_fundraise_purchase_activity(
            purchase, fundraise.unified_document, usd_cents=9999
        )
        recipient = activity.recipients.get()
        recipient.usd_cents = 9999
        recipient.save()

        # Act
        self._call()

        # Assert
        activity.refresh_from_db()
        recipient.refresh_from_db()
        self.assertEqual(activity.usd_cents, 9999)
        self.assertEqual(recipient.usd_cents, 9999)

    def test_creates_missing_usd_fundraise_payout_activities(self):
        """Creates missing USD_FUNDRAISE_PAYOUT activities from contributions."""
        # Arrange
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, target_currency="USD")
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.recipient,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.funder,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        contribution = UsdFundraiseContribution.objects.create(
            user=self.funder,
            fundraise=fundraise,
            amount_cents=10000,
            fee_cents=900,
            origin_fund_id="fund_test",
            destination_org_id="org_test",
        )

        # Act
        with patch.object(Fundraise, "get_recipient", return_value=self.recipient):
            self._call()

        # Assert
        activity = FundingActivity.objects.get(
            source_type=FundingActivity.USD_FUNDRAISE_PAYOUT,
            source_object_id=contribution.pk,
        )
        self.assertEqual(activity.usd_cents, 10000)
        self.assertEqual(activity.total_amount, Decimal("200"))
        recipient = activity.recipients.get()
        self.assertEqual(recipient.recipient_user_id, self.recipient.id)
        self.assertEqual(recipient.usd_cents, 10000)
        self.assertEqual(recipient.amount, Decimal("200"))

    def test_dry_run_produces_no_writes(self):
        """--dry-run reports work but does not write to the database."""
        # Arrange
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, target_currency="USD")
        purchase, fundraise = self._create_completed_fundraise_purchase(
            amount="100", rsc_usd_rate=0.5
        )
        activity = self._create_fundraise_purchase_activity(
            purchase, fundraise.unified_document
        )

        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.recipient,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.funder,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        UsdFundraiseContribution.objects.create(
            user=self.funder,
            fundraise=fundraise,
            amount_cents=5000,
            fee_cents=450,
            origin_fund_id="fund_dry",
            destination_org_id="org_dry",
        )

        # Act
        output = self._call("--dry-run")

        # Assert
        activity.refresh_from_db()
        self.assertEqual(activity.usd_cents, 0)
        self.assertEqual(
            FundingActivity.objects.filter(
                source_type=FundingActivity.USD_FUNDRAISE_PAYOUT
            ).count(),
            0,
        )
        self.assertIn("DRY RUN", output)
        self.assertIn("Phase 1", output)
        self.assertIn("Phase 2", output)
