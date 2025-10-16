from unittest.mock import MagicMock, call, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.signals.post_signals import handle_post_create_feed_entry
from hub.models import Hub
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestPostSignals(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testUser1")
        self.hub1 = Hub.objects.create(name="testHub1")
        self.hub2 = Hub.objects.create(name="testHub2")
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION,
        )
        self.unified_document.hubs.add(self.hub1)
        self.unified_document.hubs.add(self.hub2)
        self.post = ResearchhubPost.objects.create(
            created_by=self.user,
            unified_document=self.unified_document,
        )

    @patch("feed.signals.post_signals.create_feed_entry")
    @patch("feed.signals.post_signals.transaction")
    def test_post_create_feed_entry(self, mock_transaction, mock_create_feed_entry):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create_feed_entry.apply_async = MagicMock()

        # Act
        post = ResearchhubPost.objects.create(
            created_by=self.user,
            unified_document=self.unified_document,
        )

        # Assert
        mock_create_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        post.id,
                        ContentType.objects.get_for_model(post).id,
                        FeedEntry.PUBLISH,
                        [self.hub1.id, self.hub2.id],
                        post.created_by.id,
                    ),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.post_signals.create_feed_entry")
    @patch("feed.signals.post_signals.transaction")
    def test_handle_post_create_feed_entry(
        self, mock_transaction, mock_create_feed_entry
    ):
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create_feed_entry.apply_async = MagicMock()

        # Act
        handle_post_create_feed_entry(sender=ResearchhubPost, instance=self.post)

        # Assert
        mock_create_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        self.post.id,
                        ContentType.objects.get_for_model(self.post).id,
                        FeedEntry.PUBLISH,
                        [self.hub1.id, self.hub2.id],
                        self.post.created_by.id,
                    ),
                    priority=1,
                ),
            ]
        )
