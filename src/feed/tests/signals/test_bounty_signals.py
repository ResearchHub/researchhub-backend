from unittest.mock import call, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.signals.bounty_signals import (
    handle_boundy_closed_feed_entry,
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
    def test_handle_bounty_create_feed_entry_when_open(self, mock_create_feed_entry):
        """
        Test direct call to signal handler when bounty is open
        """

        # Act
        handle_bounty_create_feed_entry(
            sender=Bounty,
            instance=self.bounty,
            signal=None,
        )

        # Assert
        assert mock_create_feed_entry.apply_async.call_count == 2
        mock_create_feed_entry.apply_async.assert_has_calls(
            [
                # first hub
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(self.bounty).id,
                        "PUBLISH",
                        self.hub1.id,
                        ContentType.objects.get_for_model(self.hub1).id,
                    ),
                    priority=1,
                ),
                # second hub
                call(
                    args=(
                        self.bounty.id,
                        ContentType.objects.get_for_model(self.bounty).id,
                        "PUBLISH",
                        self.hub2.id,
                        ContentType.objects.get_for_model(self.hub2).id,
                    ),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.bounty_signals.create_feed_entry")
    def test_signal_fires_on_bounty_create(self, mock_create_feed_entry):
        """
        Test that signal fires and feed entries are created when bounty is opened.
        """

        # Act
        Bounty.objects.create(
            status=Bounty.OPEN,
            bounty_type=Bounty.Type.REVIEW,
            unified_document=self.researchhub_document,
            item=self.comment,
            escrow=self.escrow,
            created_by=self.user,
        )

        # Assert
        assert mock_create_feed_entry.apply_async.call_count == 2

    @patch("feed.signals.bounty_signals.delete_feed_entry")
    def test_handle_bounty_closed_feed_entry_when_closed(self, mock_delete_feed_entry):
        """
        Test direct call to signal handler when bounty is closed.
        """
        # Arrage
        self.bounty.status = Bounty.CLOSED

        # Act
        handle_boundy_closed_feed_entry(
            sender=Bounty,
            instance=self.bounty,
            signal=None,
        )

        # Assert
        assert mock_delete_feed_entry.apply_async.call_count == 2
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
    def test_signal_fires_on_bounty_closed(self, mock_delete_feed_entry):
        """
        Test that signal fires and feed entries are deleted when bounty is closed.
        """
        # Arrange
        self.bounty.status = Bounty.CLOSED

        # Act
        self.bounty.save()

        # Assert
        assert mock_delete_feed_entry.apply_async.call_count == 2
