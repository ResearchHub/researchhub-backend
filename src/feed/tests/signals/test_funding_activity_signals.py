from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from feed.models import FeedEntry
from feed.serializers import serialize_feed_item
from feed.tasks import create_feed_entry
from paper.tests.helpers import create_paper
from purchase.models import Purchase
from reputation.models import Bounty, Distribution
from reputation.related_models.escrow import Escrow, EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.services.funding_activity_service import FundingActivityService
from user.tasks.funding_activity_tasks import create_funding_activity_task
from user.tests.helpers import create_user
from utils.test_helpers import AWSMockTestCase


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class FundingActivityFeedSignalTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.funder = create_user(email="funder@test.com")
        self.recipient = create_user(email="recipient@test.com")

    @patch("feed.signals.funding_activity_signals.transaction")
    @patch("user.signals.funding_activity_signals.transaction")
    def test_bounty_payout_creates_feed_entry(
        self, mock_user_transaction, mock_feed_transaction
    ):
        """
        When a BOUNTY_PAYOUT FundingActivity is created, a feed entry is
        created with the correct content type, unified document, and funder.
        """
        # Arrange
        mock_user_transaction.on_commit = lambda func: func()
        mock_feed_transaction.on_commit = lambda func: func()

        def run_task_sync(source_type, source_id):
            create_funding_activity_task(source_type, source_id)

        with patch(
            "user.signals.funding_activity_signals.create_funding_activity_task"
        ) as mock_task:
            mock_task.delay = run_task_sync

            paper = create_paper(title="Bounty paper", uploaded_by=self.funder)
            ct_paper = ContentType.objects.get_for_model(paper.__class__)
            escrow = Escrow.objects.create(
                hold_type=Escrow.BOUNTY,
                status=Escrow.PENDING,
                created_by=self.funder,
                content_type=ct_paper,
                object_id=paper.id,
            )
            Bounty.objects.create(
                created_by=self.funder,
                bounty_type=Bounty.Type.REVIEW,
                unified_document=paper.unified_document,
                item_content_type=ct_paper,
                item_object_id=paper.id,
                escrow=escrow,
            )
            rec = EscrowRecipients.objects.create(
                escrow=escrow,
                user=self.recipient,
                amount=Decimal("25"),
            )

            # Act
            escrow.status = Escrow.PAID
            escrow.save()

        # Assert
        activity = FundingActivity.objects.get(
            source_type=FundingActivity.BOUNTY_PAYOUT,
            source_object_id=rec.pk,
        )
        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        feed_entry = FeedEntry.objects.get(
            content_type=fa_ct,
            object_id=activity.id,
            action=FeedEntry.PUBLISH,
        )
        self.assertEqual(feed_entry.unified_document_id, paper.unified_document_id)
        self.assertEqual(feed_entry.user_id, self.funder.id)
        self.assertEqual(feed_entry.action_date, activity.activity_date)

        content = serialize_feed_item(activity, fa_ct)
        self.assertEqual(content["id"], activity.id)
        self.assertEqual(content["source_type"], FundingActivity.BOUNTY_PAYOUT)
        self.assertEqual(Decimal(str(content["total_amount"])), Decimal("25"))
        self.assertEqual(content["funder"]["id"], self.funder.author_profile.id)
        self.assertEqual(len(content["recipients"]), 1)
        self.assertEqual(
            content["recipients"][0]["recipient_user"]["id"],
            self.recipient.author_profile.id,
        )

    @patch("feed.signals.funding_activity_signals.transaction")
    def test_tip_review_creates_feed_entry(self, mock_feed_transaction):
        """
        When a TIP_REVIEW FundingActivity is created, a feed entry is created
        with the correct content type, unified document, and funder.
        """
        # Arrange
        mock_feed_transaction.on_commit = lambda func: func()

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
        distribution = Distribution.objects.create(
            giver=self.funder,
            recipient=self.recipient,
            amount=Decimal("20"),
            distribution_type="PURCHASE",
            proof_item_content_type=ct_purchase,
            proof_item_object_id=proof_purchase.id,
        )

        # Act
        activity = FundingActivityService.create_funding_activity(
            FundingActivity.TIP_REVIEW,
            distribution,
        )

        # Assert
        self.assertIsNotNone(activity)
        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        feed_entry = FeedEntry.objects.get(
            content_type=fa_ct,
            object_id=activity.id,
            action=FeedEntry.PUBLISH,
        )
        self.assertEqual(
            feed_entry.unified_document_id,
            paper.unified_document_id,
        )
        self.assertEqual(feed_entry.user_id, self.funder.id)

        content = serialize_feed_item(activity, fa_ct)
        self.assertEqual(content["source_type"], FundingActivity.TIP_REVIEW)
        self.assertEqual(Decimal(str(content["total_amount"])), Decimal("20"))
        self.assertEqual(content["funder"]["id"], self.funder.author_profile.id)
        self.assertEqual(len(content["recipients"]), 1)

    def test_create_feed_entry_task_uses_activity_date(self):
        """create_feed_entry uses activity_date for FundingActivity rows."""
        # Arrange
        paper = create_paper(title="Task paper", uploaded_by=self.funder)
        activity = FundingActivity.objects.create(
            funder=self.funder,
            source_type=FundingActivity.BOUNTY_PAYOUT,
            total_amount=Decimal("10"),
            unified_document=paper.unified_document,
            activity_date=paper.created_date,
            source_content_type=ContentType.objects.get_for_model(EscrowRecipients),
            source_object_id=999_999,
        )
        FundingActivityRecipient.objects.create(
            activity=activity,
            recipient_user=self.recipient,
            amount=Decimal("10"),
        )
        fa_ct = ContentType.objects.get_for_model(FundingActivity)

        # Act
        feed_entry = create_feed_entry(
            activity.id,
            fa_ct.id,
            FeedEntry.PUBLISH,
            [],
            self.funder.id,
        )

        # Assert
        self.assertEqual(feed_entry.action_date, activity.activity_date)
