from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from paper.tests.helpers import create_paper
from purchase.models import Purchase
from purchase.related_models.fundraise_model import Fundraise
from reputation.models import Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from user.related_models.funding_activity_model import FundingActivity
from user.tests.helpers import create_user


class FundingActivitySignalsTests(TestCase):
    def setUp(self):
        self.funder = create_user(email="funder@test.com")
        self.recipient = create_user(email="recipient@test.com")

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    @patch("user.signals.funding_activity_signals.transaction")
    def test_purchase_paid_boost_schedules_task(self, mock_transaction, mock_task):
        """When Purchase is saved with PAID + BOOST, task is scheduled with TIP_DOCUMENT."""
        mock_transaction.on_commit = lambda func: func()
        from django.contrib.contenttypes.models import ContentType

        from paper.models import Paper

        paper = Paper.objects.create(
            title="Test",
            uploaded_by=self.recipient,
        )
        ct_paper = ContentType.objects.get_for_model(Paper)
        purchase = Purchase(
            user=self.funder,
            content_type=ct_paper,
            object_id=paper.id,
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
            amount="50",
            purchase_method=Purchase.OFF_CHAIN,
        )
        purchase.save()
        mock_task.delay.assert_called_once_with(
            FundingActivity.TIP_DOCUMENT,
            purchase.pk,
        )

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    def test_purchase_paid_fundraise_does_not_schedule_task(self, mock_task):
        """FUNDRAISE_CONTRIBUTION+PAID does not schedule task; payouts come from escrow PAID."""
        from django.contrib.contenttypes.models import ContentType

        from researchhub_document.related_models.researchhub_unified_document_model import (
            ResearchhubUnifiedDocument,
        )

        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )
        fundraise = Fundraise.objects.create(
            created_by=self.recipient,
            status=Fundraise.CLOSED,
            unified_document=uni_doc,
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PAID,
            created_by=self.funder,
            content_type=ct_fundraise,
            object_id=fundraise.id,
        )
        fundraise.escrow = escrow
        fundraise.save()
        purchase = Purchase(
            user=self.funder,
            content_type=ct_fundraise,
            object_id=fundraise.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="100",
            purchase_method=Purchase.OFF_CHAIN,
        )
        purchase.save()
        mock_task.delay.assert_not_called()

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    @patch("user.signals.funding_activity_signals.transaction")
    def test_escrow_paid_fundraise_schedules_task_per_contribution(
        self, mock_transaction, mock_task
    ):
        """Escrow PAID+FUNDRAISE schedules task per RSC purchase and per USD contribution."""
        mock_transaction.on_commit = lambda func: func()
        from django.contrib.contenttypes.models import ContentType

        from purchase.models import UsdFundraiseContribution
        from researchhub_document.related_models.researchhub_unified_document_model import (
            ResearchhubUnifiedDocument,
        )

        uni_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PREREGISTRATION"
        )
        fundraise = Fundraise.objects.create(
            created_by=self.recipient,
            status=Fundraise.COMPLETED,
            unified_document=uni_doc,
        )
        ct_fundraise = ContentType.objects.get_for_model(Fundraise)
        escrow = Escrow.objects.create(
            hold_type=Escrow.FUNDRAISE,
            status=Escrow.PENDING,
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
            amount="100",
            purchase_method=Purchase.OFF_CHAIN,
        )
        usd_contribution = UsdFundraiseContribution.objects.create(
            user=self.funder,
            fundraise=fundraise,
            amount_cents=5000,
            fee_cents=450,
            amount_rsc=Decimal("500"),
        )
        escrow.status = Escrow.PAID
        escrow.save()
        self.assertEqual(mock_task.delay.call_count, 2)
        mock_task.delay.assert_any_call(
            FundingActivity.FUNDRAISE_PAYOUT,
            purchase.pk,
        )
        mock_task.delay.assert_any_call(
            FundingActivity.FUNDRAISE_PAYOUT_USD,
            usd_contribution.pk,
        )

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    def test_purchase_pending_does_not_schedule_task(self, mock_task):
        """When Purchase is saved with PENDING, task is not scheduled."""
        from django.contrib.contenttypes.models import ContentType

        from paper.tests.helpers import create_paper

        paper = create_paper(title="Test", uploaded_by=self.recipient)
        ct_paper = ContentType.objects.get_for_model(paper.__class__)
        purchase = Purchase(
            user=self.funder,
            content_type=ct_paper,
            object_id=paper.id,
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PENDING,
            amount="50",
            purchase_method=Purchase.OFF_CHAIN,
        )
        purchase.save()
        mock_task.delay.assert_not_called()

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    @patch("user.signals.funding_activity_signals.transaction")
    def test_escrow_paid_bounty_schedules_task_per_recipient(
        self, mock_transaction, mock_task
    ):
        """When Escrow is saved with PAID + BOUNTY, task is scheduled for each EscrowRecipients."""
        mock_transaction.on_commit = lambda func: func()
        from django.contrib.contenttypes.models import ContentType

        from paper.tests.helpers import create_paper
        from reputation.models import Bounty

        paper = create_paper(title="Bounty paper", uploaded_by=self.funder)
        ct_paper = ContentType.objects.get_for_model(paper.__class__)
        escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            status=Escrow.PENDING,
            created_by=self.funder,
            content_type=ct_paper,
            object_id=paper.id,
        )
        bounty = Bounty.objects.create(
            created_by=self.funder,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=paper.unified_document,
            item_content_type=ct_paper,
            item_object_id=paper.id,
            escrow=escrow,
        )
        rec = EscrowRecipients.objects.create(
            escrow=escrow, user=self.recipient, amount=Decimal("25")
        )
        escrow.status = Escrow.PAID
        escrow.save()
        self.assertEqual(mock_task.delay.call_count, 1)
        mock_task.delay.assert_called_with(FundingActivity.BOUNTY_PAYOUT, rec.pk)

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    @patch("user.signals.funding_activity_signals.transaction")
    def test_distribution_created_purchase_schedules_task(
        self, mock_transaction, mock_task
    ):
        """When Distribution is created with PURCHASE (proof = Purchase on review comment), task is scheduled with TIP_REVIEW."""
        mock_transaction.on_commit = lambda func: func()
        paper = create_paper(title="Review paper", uploaded_by=self.recipient)
        thread = RhCommentThreadModel.objects.create(
            content_object=paper,
            created_by=self.recipient,
            updated_by=self.recipient,
        )
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.recipient,
            updated_by=self.recipient,
            comment_type=PEER_REVIEW,
            comment_content_json={"ops": [{"insert": "Review comment"}]},
        )
        ct_comment = ContentType.objects.get_for_model(RhCommentModel)
        proof_purchase = Purchase.objects.create(
            user=self.funder,
            content_type=ct_comment,
            object_id=comment.id,
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
            amount=Decimal("20"),
            purchase_method=Purchase.OFF_CHAIN,
        )
        ct_purchase = ContentType.objects.get_for_model(Purchase)
        dist = Distribution.objects.create(
            giver=self.funder,
            recipient=self.recipient,
            amount=Decimal("20"),
            distribution_type="PURCHASE",
            proof_item_content_type=ct_purchase,
            proof_item_object_id=proof_purchase.id,
        )
        mock_task.delay.assert_called_once_with(
            FundingActivity.TIP_REVIEW,
            dist.pk,
        )

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    @patch("user.signals.funding_activity_signals.transaction")
    def test_distribution_created_fee_schedules_task(self, mock_transaction, mock_task):
        """When Distribution is created with fee type, task is scheduled with FEE."""
        mock_transaction.on_commit = lambda func: func()
        dist = Distribution.objects.create(
            giver=self.funder,
            amount=Decimal("5"),
            distribution_type="BOUNTY_DAO_FEE",
        )
        mock_task.delay.assert_called_once_with(
            FundingActivity.FEE,
            dist.pk,
        )

    @patch("user.signals.funding_activity_signals.create_funding_activity_task")
    def test_distribution_updated_does_not_schedule_task(self, mock_task):
        """When Distribution is updated (not created), task is not scheduled."""
        dist = Distribution.objects.create(
            giver=self.funder,
            amount=Decimal("5"),
            distribution_type="BOUNTY_RH_FEE",
        )
        mock_task.reset_mock()
        dist.amount = Decimal("10")
        dist.save()
        mock_task.delay.assert_not_called()
        mock_task.reset_mock()
        dist.amount = Decimal("10")
        dist.save()
        mock_task.delay.assert_not_called()
