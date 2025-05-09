from unittest.mock import MagicMock, call, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from purchase.related_models.purchase_model import Purchase
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_user


class TestPurchaseSignals(TestCase):
    def setUp(self):
        self.user = create_user("test@example.com", "password")

        # Create a unified document
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.POSTS,
        )

        # Create a post connected to the unified document
        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            unified_document=self.unified_document,
            created_by=self.user,
        )

        # Create a feed entry for the post
        self.post_content_type = ContentType.objects.get_for_model(self.post)
        self.feed_entry = FeedEntry.objects.create(
            content_type=self.post_content_type,
            object_id=self.post.id,
            action="PUBLISH",
            action_date=self.post.created_date,
            user=self.user,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

    @patch("feed.signals.purchase_signals.refresh_feed_entry")
    @patch("feed.signals.purchase_signals.transaction")
    def test_refresh_feed_entries_on_purchase_create(
        self,
        mock_transaction,
        mock_refresh_feed_entry,
    ):
        """Test that feed entries are refreshed when a purchase is created"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Act
        Purchase.objects.create(
            user=self.user,
            content_type=self.post_content_type,
            object_id=self.post.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="10.0",
        )

        # Assert
        mock_refresh_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(self.feed_entry.id,),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.purchase_signals.refresh_feed_entry")
    @patch("feed.signals.purchase_signals.transaction")
    def test_refresh_feed_entries_on_purchase_update(
        self,
        mock_transaction,
        mock_refresh_feed_entry,
    ):
        """Test that feed entries are refreshed when a purchase is updated"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Act
        Purchase.objects.create(
            user=self.user,
            content_type=self.post_content_type,
            object_id=self.post.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="10.0",
        )

        # Assert
        mock_refresh_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(self.feed_entry.id,),
                    priority=1,
                ),
            ]
        )
