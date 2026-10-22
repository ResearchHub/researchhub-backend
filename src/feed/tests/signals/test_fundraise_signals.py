from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from feed.models import FeedEntry
from feed.serializers import serialize_feed_item
from feed.tasks import create_feed_entry
from purchase.models import Fundraise
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_user
from utils.test_helpers import AWSMockTestCase


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class FundraiseCompletedFeedSignalTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.user = create_user(email="proposer@test.com")
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.post = ResearchhubPost.objects.create(
            title="Funded Proposal",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=self.unified_document,
        )
        self.fundraise = Fundraise.objects.create(
            unified_document=self.unified_document,
            created_by=self.user,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )
        self.fundraise_ct = ContentType.objects.get_for_model(Fundraise)

    @patch("feed.signals.fundraise_signals.transaction")
    def test_completing_fundraise_creates_feed_entry(self, mock_transaction):
        """Transitioning a fundraise to COMPLETED creates a feed entry."""
        # Arrange
        mock_transaction.on_commit = lambda func: func()

        # Act
        self.fundraise.status = Fundraise.COMPLETED
        self.fundraise.save()

        # Assert
        feed_entry = FeedEntry.objects.get(
            content_type=self.fundraise_ct,
            object_id=self.fundraise.id,
            action=FeedEntry.PUBLISH,
        )
        self.assertEqual(
            feed_entry.unified_document_id,
            self.unified_document.id,
        )
        self.assertEqual(feed_entry.user_id, self.user.id)
        self.assertEqual(feed_entry.action_date, self.fundraise.updated_date)

        content = serialize_feed_item(self.fundraise, self.fundraise_ct)
        self.assertEqual(content["id"], self.fundraise.id)
        self.assertEqual(content["status"], Fundraise.COMPLETED)
        self.assertEqual(content["proposal_title"], self.post.title)
        self.assertEqual(content["post_id"], self.post.id)
        self.assertEqual(
            content["unified_document_id"],
            self.unified_document.id,
        )
        self.assertEqual(content["goal_amount"]["usd"], 1000.0)

    @patch("feed.signals.fundraise_signals.transaction")
    def test_already_completed_save_does_not_duplicate(self, mock_transaction):
        """Saving an already-COMPLETED fundraise does not create another entry."""
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        self.fundraise.status = Fundraise.COMPLETED
        self.fundraise.save()
        first_count = FeedEntry.objects.filter(
            content_type=self.fundraise_ct,
            object_id=self.fundraise.id,
        ).count()

        # Act
        self.fundraise.goal_amount = Decimal("1500.00")
        self.fundraise.save()

        # Assert
        self.assertEqual(first_count, 1)
        self.assertEqual(
            FeedEntry.objects.filter(
                content_type=self.fundraise_ct,
                object_id=self.fundraise.id,
            ).count(),
            1,
        )

    @patch("feed.signals.fundraise_signals.transaction")
    def test_open_fundraise_save_does_not_create_feed_entry(self, mock_transaction):
        """Saving an OPEN fundraise does not create a completion feed entry."""
        # Arrange
        mock_transaction.on_commit = lambda func: func()

        # Act
        self.fundraise.goal_amount = Decimal("2000.00")
        self.fundraise.save()

        # Assert
        self.assertFalse(
            FeedEntry.objects.filter(
                content_type=self.fundraise_ct,
                object_id=self.fundraise.id,
            ).exists()
        )

    @patch("feed.signals.fundraise_signals.create_feed_entry")
    def test_create_feed_entry_task_uses_updated_date(self, _mock_create):
        """create_feed_entry uses updated_date for Fundraise rows."""
        # Arrange — bump updated_date without relying on the completion signal
        self.fundraise.goal_amount = Decimal("1100.00")
        self.fundraise.save()
        self.fundraise.refresh_from_db()

        # Act
        feed_entry = create_feed_entry(
            self.fundraise.id,
            self.fundraise_ct.id,
            FeedEntry.PUBLISH,
            [],
            self.user.id,
        )

        # Assert
        self.assertEqual(feed_entry.action_date, self.fundraise.updated_date)
