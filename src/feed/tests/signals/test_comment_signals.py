from unittest.mock import MagicMock, call, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.tests.test_views import User
from hub.models import Hub
from paper.related_models.paper_model import Paper
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)


class CommentSignalsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.hub1 = Hub.objects.create(name="hub1")
        self.hub2 = Hub.objects.create(name="hub2")
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.DISCUSSION,
        )
        self.unified_document.hubs.add(self.hub1)
        self.unified_document.hubs.add(self.hub2)
        self.paper = Paper.objects.create(
            title="paper1", unified_document=self.unified_document
        )

        self.content_type = ContentType.objects.get_for_model(Paper)
        self.thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=self.content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )
        self.comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "comment1"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            thread=self.thread,
        )

    @patch("feed.signals.comment_signals.create_feed_entry")
    @patch("feed.signals.comment_signals.transaction")
    def test_handle_comment_created_signal(
        self, mock_transaction, mock_create_feed_entry
    ):
        """
        Test that a feed entry is created when a comment is created.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create_feed_entry.apply_async = MagicMock()

        # Act
        comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "comment1"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            thread=self.thread,
        )

        # Assert
        mock_create_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        comment.id,
                        ContentType.objects.get_for_model(RhCommentModel).id,
                        FeedEntry.PUBLISH,
                        self.hub1.id,
                        ContentType.objects.get_for_model(Hub).id,
                        self.user.id,
                    ),
                    priority=1,
                ),
                call(
                    args=(
                        comment.id,
                        ContentType.objects.get_for_model(RhCommentModel).id,
                        FeedEntry.PUBLISH,
                        self.hub2.id,
                        ContentType.objects.get_for_model(Hub).id,
                        self.user.id,
                    ),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.comment_signals.create_feed_entry")
    @patch("feed.signals.comment_signals.transaction")
    def test_handle_comment_created_signal_ignores_non_peer_review_comments(
        self, mock_transaction, mock_create_feed_entry
    ):
        """
        Test that a feed entry is not created when a non-peer review comment is created.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create_feed_entry.apply_async = MagicMock()

        # Act
        RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "comment1"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=self.thread,
        )

        # Assert
        mock_create_feed_entry.apply_async.assert_not_called()

    @patch("feed.signals.comment_signals.delete_feed_entry")
    @patch("feed.signals.comment_signals.transaction")
    def test_handle_comment_removed_signal(
        self, mock_transaction, mock_delete_feed_entry
    ):
        """
        Test that a feed entry is deleted when a comment is removed.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_delete_feed_entry.apply_async = MagicMock()

        # Act
        self.comment.is_removed = True
        self.comment.save()

        # Assert
        mock_delete_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        self.comment.id,
                        ContentType.objects.get_for_model(RhCommentModel).id,
                        self.hub1.id,
                        ContentType.objects.get_for_model(Hub).id,
                    ),
                    priority=1,
                ),
                call(
                    args=(
                        self.comment.id,
                        ContentType.objects.get_for_model(RhCommentModel).id,
                        self.hub2.id,
                        ContentType.objects.get_for_model(Hub).id,
                    ),
                    priority=1,
                ),
            ]
        )
