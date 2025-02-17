from unittest.mock import MagicMock, call, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.signals.bounty_signals import (
    handle_boundy_delete_feed_entry,
    handle_bounty_create_feed_entry,
)
from hub.models import Hub
from paper.related_models.paper_model import Paper
from reputation.related_models.bounty import Bounty
from reputation.related_models.escrow import Escrow
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.user_model import User


class TestBountySignals(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="testUser1")

        self.paper = Paper.objects.create(title="testPaper1")
        content_type = ContentType.objects.get_for_model(self.paper)

        self.review_thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )

        self.comment = RhCommentModel.objects.create(
            thread=self.review_thread,
            created_by=self.user,
        )

        self.researchhub_document = ResearchhubUnifiedDocument.objects.create()
        self.hub1 = Hub.objects.create(name="testHub1")
        self.hub2 = Hub.objects.create(name="testHub2")
        self.researchhub_document.hubs.add(self.hub1)
        self.researchhub_document.hubs.add(self.hub2)

        self.escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            item=self.researchhub_document,
        )

        self.bounty = Bounty.objects.create(
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.researchhub_document,
            item=self.comment,
            escrow=self.escrow,
            created_by=self.user,
        )

    @patch("feed.signals.bounty_signals.create_feed_entry")
    @patch("feed.signals.bounty_signals.transaction")
    def test_create_feed_entries_for_open_bounty(
        self, mock_transaction, mock_create_feed_entry
    ):
        """
        Test that feed entries are created for an open bounty.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create_feed_entry.apply_async = MagicMock()

        # Act
        bounty = Bounty.objects.create(
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.researchhub_document,
            item=self.comment,
            escrow=self.escrow,
            created_by=self.user,
        )

        # Assert
        mock_create_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        bounty.id,
                        ContentType.objects.get_for_model(Bounty).id,
                        FeedEntry.OPEN,
                        self.hub1.id,
                        ContentType.objects.get_for_model(Hub).id,
                        bounty.created_by.id,
                    ),
                    priority=1,
                ),
                call(
                    args=(
                        bounty.id,
                        ContentType.objects.get_for_model(Bounty).id,
                        FeedEntry.OPEN,
                        self.hub2.id,
                        ContentType.objects.get_for_model(Hub).id,
                        bounty.created_by.id,
                    ),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.bounty_signals.create_feed_entry")
    @patch("feed.signals.bounty_signals.transaction")
    def test_handle_bounty_create_feed_entry(
        self, mock_transaction, mock_create_feed_entry
    ):
        """
        Test direct call to handle_bounty_create_feed_entry signal handler.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_create_feed_entry.apply_async = MagicMock()

        # Act
        handle_bounty_create_feed_entry(sender=Bounty, instance=self.bounty)

        # Assert
        mock_create_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(Bounty).id,
                        FeedEntry.OPEN,
                        self.hub1.id,
                        ContentType.objects.get_for_model(Hub).id,
                        self.bounty.created_by.id,
                    ),
                    priority=1,
                ),
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(Bounty).id,
                        FeedEntry.OPEN,
                        self.hub2.id,
                        ContentType.objects.get_for_model(Hub).id,
                        self.bounty.created_by.id,
                    ),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.bounty_signals.delete_feed_entry")
    @patch("feed.signals.bounty_signals.transaction")
    def test_delete_feed_entries_for_closed_bounty(
        self, mock_transaction, mock_delete_feed_entry
    ):
        """
        Test that feed entries are deleted for a closed bounty.
        """
        # Arrage
        mock_transaction.on_commit = lambda func: func()
        mock_delete_feed_entry.apply_async = MagicMock()

        # Act
        self.bounty.status = Bounty.CLOSED
        self.bounty.save()

        # Assert
        mock_delete_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(self.bounty).id,
                        self.hub1.id,
                        ContentType.objects.get_for_model(self.hub1).id,
                    ),
                    priority=1,
                ),
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(self.bounty).id,
                        self.hub2.id,
                        ContentType.objects.get_for_model(self.hub2).id,
                    ),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.bounty_signals.delete_feed_entry")
    @patch("feed.signals.bounty_signals.transaction")
    def test_handle_boundy_delete_feed_entry(
        self, mock_transaction, mock_delete_feed_entry
    ):
        """
        Test direct call to handle_boundy_delete_feed_entry signal handler.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_delete_feed_entry.apply_async = MagicMock()
        self.bounty.status = Bounty.CLOSED

        # Act
        handle_boundy_delete_feed_entry(sender=Bounty, instance=self.bounty)

        # Assert
        mock_delete_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(Bounty).id,
                        self.hub1.id,
                        ContentType.objects.get_for_model(Hub).id,
                    ),
                    priority=1,
                ),
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(Bounty).id,
                        self.hub2.id,
                        ContentType.objects.get_for_model(Hub).id,
                    ),
                    priority=1,
                ),
            ]
        )
