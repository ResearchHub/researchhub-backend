from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from feed.models import FeedEntry
from feed.signals.bounty_signals import (
    handle_bounty_delete_update_feed_entries,
    handle_bounty_update_feed_entries,
)
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from reputation.models import Bounty, Escrow
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import DISCUSSION
from user.tests.helpers import create_random_default_user


class BountySignalsTests(TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def setUp(self):
        self.user = create_random_default_user("bounty_signals_test")
        self.hub = create_hub(name="Test Hub")

        # Create a paper with unified document
        self.paper = create_paper(title="Test Paper", uploaded_by=self.user)
        self.paper.unified_document.hubs.add(self.hub)

        # Create a post with unified document
        self.post = create_post(
            title="Test Post", created_by=self.user, document_type=DISCUSSION
        )
        self.post.unified_document.hubs.add(self.hub)

        # Create a comment
        self.comment = create_rh_comment(created_by=self.user, paper=self.paper)

        # Create escrows for bounties
        self.paper_escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=100,
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
        )

        self.post_escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=200,
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
        )

        self.comment_escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=50,
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.id,
        )

        # Create feed entries for our test
        paper_content_type = ContentType.objects.get_for_model(self.paper)
        hub_content_type = ContentType.objects.get_for_model(self.hub)
        post_content_type = ContentType.objects.get_for_model(self.post)
        comment_content_type = ContentType.objects.get_for_model(self.comment)

        # Paper feed entry
        self.paper_feed_entry = FeedEntry.objects.create(
            content_type=paper_content_type,
            object_id=self.paper.id,
            parent_content_type=hub_content_type,
            parent_object_id=self.hub.id,
            action=FeedEntry.PUBLISH,
            action_date=self.paper.created_date,
            user=self.user,
            unified_document=self.paper.unified_document,
            content={},
            metrics={},
        )

        # Post feed entry
        self.post_feed_entry = FeedEntry.objects.create(
            content_type=post_content_type,
            object_id=self.post.id,
            parent_content_type=hub_content_type,
            parent_object_id=self.hub.id,
            action=FeedEntry.PUBLISH,
            action_date=self.post.created_date,
            user=self.user,
            unified_document=self.post.unified_document,
            content={},
            metrics={},
        )

        # Comment feed entry
        self.comment_feed_entry = FeedEntry.objects.create(
            content_type=comment_content_type,
            object_id=self.comment.id,
            parent_content_type=hub_content_type,
            parent_object_id=self.hub.id,
            action=FeedEntry.PUBLISH,
            action_date=self.comment.created_date,
            user=self.user,
            unified_document=self.paper.unified_document,
            content={},
            metrics={},
        )

    @patch("feed.signals.bounty_signals.refresh_feed_entries_for_objects")
    def test_bounty_create_updates_paper_feed_entries(self, mock_refresh_feed_entry):
        """Test that creating a bounty for a paper updates the paper's feed entries"""
        # Arrange
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Act - Create a bounty for the paper
        Bounty.objects.create(
            amount=100,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.paper.unified_document,
            item_content_type=ContentType.objects.get_for_model(self.paper),
            item_object_id=self.paper.id,
            escrow=self.paper_escrow,
            created_by=self.user,
        )

        # Assert
        self.assertTrue(mock_refresh_feed_entry.apply_async.called)
        # Verify correct args were passed
        paper_content_type = ContentType.objects.get_for_model(self.paper)
        mock_refresh_feed_entry.apply_async.assert_called_with(
            args=(self.paper.id, paper_content_type.id),
            priority=1,
        )

    @patch("feed.signals.bounty_signals.refresh_feed_entries_for_objects")
    def test_bounty_create_updates_post_feed_entries(self, mock_refresh_feed_entry):
        """Test that creating a bounty for a post updates the post's feed entries"""
        # Arrange
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Act
        Bounty.objects.create(
            amount=200,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.ANSWER,
            unified_document=self.post.unified_document,
            item_content_type=ContentType.objects.get_for_model(self.post),
            item_object_id=self.post.id,
            escrow=self.post_escrow,
            created_by=self.user,
        )

        # Assert
        self.assertTrue(mock_refresh_feed_entry.apply_async.called)
        # Verify correct args were passed
        post_content_type = ContentType.objects.get_for_model(self.post)
        mock_refresh_feed_entry.apply_async.assert_called_with(
            args=(self.post.id, post_content_type.id),
            priority=1,
        )

    @patch("feed.signals.bounty_signals.refresh_feed_entries_for_objects")
    def test_bounty_status_change_updates_feed_entries(self, mock_refresh_feed_entry):
        """Test that changing a bounty's status updates the document's feed entries"""
        # Arrange
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Create a bounty for the paper
        bounty = Bounty.objects.create(
            amount=100,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.paper.unified_document,
            item_content_type=ContentType.objects.get_for_model(self.paper),
            item_object_id=self.paper.id,
            escrow=self.paper_escrow,
            created_by=self.user,
        )

        # Reset the mock to clear the creation call
        mock_refresh_feed_entry.apply_async.reset_mock()

        # Act - Change bounty status to CLOSED
        bounty.status = Bounty.CLOSED
        bounty.save()

        # Assert
        self.assertTrue(mock_refresh_feed_entry.apply_async.called)
        # Verify correct args were passed
        paper_content_type = ContentType.objects.get_for_model(self.paper)
        mock_refresh_feed_entry.apply_async.assert_called_with(
            args=(self.paper.id, paper_content_type.id),
            priority=1,
        )

    @patch("feed.signals.bounty_signals.refresh_feed_entries_for_objects")
    def test_bounty_for_comment_updates_feed_entries(self, mock_refresh_feed_entry):
        """Test that bounty for comment updates both feed entries"""
        # Arrange
        mock_refresh_feed_entry.apply_async = MagicMock()

        # Set the comment's thread to be on the paper
        content_type = ContentType.objects.get_for_model(self.paper)
        self.comment.thread.content_type = content_type
        self.comment.thread.object_id = self.paper.id
        self.comment.thread.save()

        # Associate the comment with the paper's unified_document via the thread
        # Cannot directly set unified_document property
        self.comment.thread.content_object.unified_document = (
            self.paper.unified_document
        )
        self.comment.thread.save()

        # Act - Create a bounty for the comment
        Bounty.objects.create(
            amount=50,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.ANSWER,
            unified_document=self.paper.unified_document,
            item_content_type=ContentType.objects.get_for_model(self.comment),
            item_object_id=self.comment.id,
            escrow=self.comment_escrow,
            created_by=self.user,
        )

        # Assert - feed entry should be updated
        self.assertTrue(mock_refresh_feed_entry.apply_async.called)
        # Verify correct args were passed
        paper_content_type = ContentType.objects.get_for_model(self.paper)
        mock_refresh_feed_entry.apply_async.assert_called_with(
            args=(self.paper.id, paper_content_type.id),
            priority=1,
        )

    @patch("feed.signals.bounty_signals.refresh_feed_entries_for_objects")
    def test_bounty_delete_updates_feed_entries(self, mock_refresh_feed_entries):
        """Test that deleting a bounty updates the document's feed entries"""
        # Arrange
        mock_refresh_feed_entries.apply_async = MagicMock()

        # Create a bounty for the post
        bounty = Bounty.objects.create(
            amount=200,
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.ANSWER,
            unified_document=self.post.unified_document,
            item_content_type=ContentType.objects.get_for_model(self.post),
            item_object_id=self.post.id,
            escrow=self.post_escrow,
            created_by=self.user,
        )

        # Reset the mock to clear the creation call
        mock_refresh_feed_entries.apply_async.reset_mock()

        # Act
        handle_bounty_delete_update_feed_entries(sender=Bounty, instance=bounty)

        # Assert
        self.assertTrue(mock_refresh_feed_entries.apply_async.called)
        # Verify correct args were passed
        post_content_type = ContentType.objects.get_for_model(self.post)
        mock_refresh_feed_entries.apply_async.assert_called_with(
            args=(self.post.id, post_content_type.id),
            priority=1,
        )
