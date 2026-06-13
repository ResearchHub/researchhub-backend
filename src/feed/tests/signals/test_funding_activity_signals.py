from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.utils import timezone

from feed.models import FeedEntry
from purchase.related_models.purchase_model import Purchase
from reputation.models import Distribution
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.funding_activity_model import FundingActivity
from user.tests.helpers import create_user
from utils.test_helpers import AWSMockTestCase


class TestFundingActivitySignals(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.funder = create_user(email="fa_signal_funder@test.com")
        self.recipient = create_user(email="fa_signal_recipient@test.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.post = ResearchhubPost.objects.create(
            title="FA Signal Proposal",
            created_by=self.funder,
            document_type=PREREGISTRATION,
            unified_document=self.unified_doc,
        )
        self.user_ct = ContentType.objects.get_for_model(self.funder)

    def _create_activity(self, source_type, source_object_id_offset=0):
        return FundingActivity.objects.create(
            funder=self.funder,
            source_type=source_type,
            total_amount=Decimal("50"),
            total_usd_cents=2500,
            unified_document=self.unified_doc,
            activity_date=timezone.now(),
            source_content_type=self.user_ct,
            source_object_id=self.funder.id + source_object_id_offset,
        )

    @patch("feed.signals.funding_activity_signals.create_feed_entry")
    @patch("feed.signals.funding_activity_signals.transaction")
    def test_bounty_payout_triggers_create_feed_entry(
        self, mock_transaction, mock_create
    ):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create.apply_async = MagicMock()

        # Act
        activity = self._create_activity(FundingActivity.BOUNTY_PAYOUT)

        # Assert
        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        mock_create.apply_async.assert_called_once_with(
            args=(
                activity.id,
                fa_ct.id,
                FeedEntry.PUBLISH,
                list(self.unified_doc.hubs.values_list("id", flat=True)),
                self.funder.id,
            ),
            priority=1,
        )

    @patch("feed.signals.funding_activity_signals.create_feed_entry")
    @patch("feed.signals.funding_activity_signals.transaction")
    def test_tip_review_triggers_create_feed_entry(self, mock_transaction, mock_create):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create.apply_async = MagicMock()

        # Act
        activity = self._create_activity(FundingActivity.TIP_REVIEW, 1000)

        # Assert
        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        mock_create.apply_async.assert_called_once_with(
            args=(
                activity.id,
                fa_ct.id,
                FeedEntry.PUBLISH,
                list(self.unified_doc.hubs.values_list("id", flat=True)),
                self.funder.id,
            ),
            priority=1,
        )

    @patch("feed.signals.funding_activity_signals.create_feed_entry")
    @patch("feed.signals.funding_activity_signals.transaction")
    def test_ignored_source_types_do_not_trigger_create_feed_entry(
        self, mock_transaction, mock_create
    ):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create.apply_async = MagicMock()

        ignored_types = [
            FundingActivity.FUNDRAISE_PAYOUT,
            FundingActivity.FEE,
            FundingActivity.TIP_DOCUMENT,
        ]

        # Act
        for idx, source_type in enumerate(ignored_types):
            self._create_activity(source_type, 2000 + idx)

        # Assert
        mock_create.apply_async.assert_not_called()

    @patch("feed.signals.funding_activity_signals.create_feed_entry")
    @patch("feed.signals.funding_activity_signals.transaction")
    def test_update_does_not_trigger_create_feed_entry(
        self, mock_transaction, mock_create
    ):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create.apply_async = MagicMock()
        activity = self._create_activity(FundingActivity.BOUNTY_PAYOUT, 3000)
        mock_create.apply_async.reset_mock()

        # Act
        activity.total_amount = Decimal("75")
        activity.save()

        # Assert
        mock_create.apply_async.assert_not_called()

    @patch("feed.signals.funding_activity_signals.create_feed_entry")
    @patch("feed.signals.funding_activity_signals.transaction")
    def test_missing_unified_document_skips_create_feed_entry(
        self, mock_transaction, mock_create
    ):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create.apply_async = MagicMock()

        # Act
        FundingActivity.objects.create(
            funder=self.funder,
            source_type=FundingActivity.BOUNTY_PAYOUT,
            total_amount=Decimal("50"),
            unified_document=None,
            activity_date=timezone.now(),
            source_content_type=self.user_ct,
            source_object_id=self.funder.id + 4000,
        )

        # Assert
        mock_create.apply_async.assert_not_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("feed.signals.funding_activity_signals.transaction")
    def test_bounty_payout_creates_feed_entry_on_commit(self, mock_transaction):
        # Arrange
        mock_transaction.on_commit = lambda func: func()

        # Act
        activity = self._create_activity(FundingActivity.BOUNTY_PAYOUT, 5000)

        # Assert
        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        self.assertTrue(
            FeedEntry.objects.filter(
                content_type=fa_ct,
                object_id=activity.id,
                action=FeedEntry.PUBLISH,
            ).exists()
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("feed.signals.funding_activity_signals.transaction")
    def test_tip_review_creates_feed_entry_with_comment_source(self, mock_transaction):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        post_ct = ContentType.objects.get_for_model(ResearchhubPost)
        thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=post_ct,
            object_id=self.post.id,
            created_by=self.recipient,
        )
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "peer review tip"}]},
            comment_type=PEER_REVIEW,
            created_by=self.recipient,
            thread=thread,
        )
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        proof_purchase = Purchase.objects.create(
            user=self.funder,
            content_type=comment_ct,
            object_id=comment.id,
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
            amount=Decimal("20"),
            purchase_method=Purchase.OFF_CHAIN,
        )
        purchase_ct = ContentType.objects.get_for_model(Purchase)
        distribution = Distribution.objects.create(
            giver=self.funder,
            recipient=self.recipient,
            amount=Decimal("20"),
            distribution_type="PURCHASE",
            proof_item_content_type=purchase_ct,
            proof_item_object_id=proof_purchase.id,
        )
        dist_ct = ContentType.objects.get_for_model(Distribution)

        # Act
        activity = FundingActivity.objects.create(
            funder=self.funder,
            source_type=FundingActivity.TIP_REVIEW,
            total_amount=Decimal("20"),
            total_usd_cents=1000,
            unified_document=self.unified_doc,
            activity_date=timezone.now(),
            source_content_type=dist_ct,
            source_object_id=distribution.id,
        )

        # Assert
        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        feed_entry = FeedEntry.objects.get(
            content_type=fa_ct,
            object_id=activity.id,
            action=FeedEntry.PUBLISH,
        )
        self.assertEqual(feed_entry.content["source_type"], FundingActivity.TIP_REVIEW)
        self.assertEqual(feed_entry.content["comment"]["id"], comment.id)
        self.assertEqual(feed_entry.content["comment"]["comment_type"], PEER_REVIEW)
