from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.models import UsdFundraiseContribution
from purchase.related_models.fundraise_model import Fundraise
from reputation.models import Distribution
from reputation.related_models.escrow import Escrow
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.funding_activity_model import FundingActivity
from user.tasks.funding_activity_tasks import create_funding_activity_task
from user.tests.helpers import create_user


class CreateFundingActivityTaskTests(TestCase):
    def setUp(self):
        self.funder = create_user(email="funder@test.com")
        self.recipient = create_user(email="recipient@test.com")

    def test_task_creates_activity_for_fee_distribution(self):
        """Task creates FundingActivity when given valid FEE (Distribution) source."""
        dist = Distribution.objects.create(
            giver=self.funder,
            recipient=None,
            amount=Decimal("10"),
            distribution_type="BOUNTY_RH_FEE",
        )
        create_funding_activity_task(FundingActivity.FEE, dist.pk)
        self.assertEqual(FundingActivity.objects.count(), 1)
        activity = FundingActivity.objects.get()
        self.assertEqual(activity.source_type, FundingActivity.FEE)
        self.assertEqual(activity.total_amount, Decimal("10"))
        self.assertEqual(activity.funder_id, self.funder.id)

    def test_task_idempotent_for_same_source(self):
        """Calling the task twice for the same source does not duplicate activity."""
        dist = Distribution.objects.create(
            giver=self.funder,
            amount=Decimal("5"),
            distribution_type="SUPPORT_RH_FEE",
        )
        create_funding_activity_task(FundingActivity.FEE, dist.pk)
        create_funding_activity_task(FundingActivity.FEE, dist.pk)
        self.assertEqual(FundingActivity.objects.count(), 1)

    def test_task_returns_when_source_missing(self):
        """Task returns without raising when source_id does not exist."""
        create_funding_activity_task(FundingActivity.FEE, 999999)
        self.assertEqual(FundingActivity.objects.count(), 0)

    def test_task_returns_when_source_type_unknown(self):
        """Task returns without raising when source_type is unknown."""
        dist = Distribution.objects.create(
            giver=self.funder,
            amount=Decimal("1"),
            distribution_type="BOUNTY_RH_FEE",
        )
        create_funding_activity_task("UNKNOWN_TYPE", dist.pk)
        self.assertEqual(FundingActivity.objects.count(), 0)

    @patch.object(Fundraise, "get_recipient")
    def test_task_creates_activity_for_fundraise_payout_usd(self, mock_get_recipient):
        """Task creates FundingActivity when given valid FUNDRAISE_PAYOUT_USD (UsdFundraiseContribution) source."""
        mock_get_recipient.return_value = self.recipient
        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION",
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        fundraise = Fundraise.objects.create(
            created_by=self.recipient,
            status=Fundraise.COMPLETED,
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
            amount_cents=5000,
            fee_cents=450,
            amount_rsc=Decimal("500"),
            is_refunded=False,
        )
        create_funding_activity_task(
            FundingActivity.FUNDRAISE_PAYOUT_USD, contribution.pk
        )
        self.assertEqual(FundingActivity.objects.count(), 1)
        activity = FundingActivity.objects.get()
        self.assertEqual(activity.source_type, FundingActivity.FUNDRAISE_PAYOUT_USD)
        self.assertEqual(activity.total_amount, Decimal("500"))
        self.assertEqual(activity.funder_id, self.funder.id)
