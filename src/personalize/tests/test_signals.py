from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.models import Vote
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from user.tests.helpers import create_random_default_user


class UnifiedDocumentSignalTests(TestCase):
    """Tests for unified document creation triggering personalize sync."""

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_queues_task_on_creation(self, mock_sync_task):
        """Creating a unified document should queue the sync task."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_removed=False
        )

        mock_sync_task.delay.assert_called_once_with(unified_doc.id)

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_skips_on_update(self, mock_sync_task):
        """Updating a unified document should not queue the sync task."""
        user = create_random_default_user("update_test_user")
        post = create_post(created_by=user)

        mock_sync_task.reset_mock()

        post.unified_document.score = 100
        post.unified_document.save()

        mock_sync_task.delay.assert_not_called()

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_triggers_when_post_created(self, mock_sync_task):
        """Creating a post queues the sync task."""
        user = create_random_default_user("post_signal_user")
        post = create_post(created_by=user)

        mock_sync_task.delay.assert_called_with(post.unified_document.id)


class VoteSignalTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("vote_test_user")
        self.post = create_post(created_by=self.user)
        self.content_type = ContentType.objects.get_for_model(self.post)

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.vote_signals.transaction")
    def test_signal_queues_task_on_upvote_creation(self, mock_transaction, mock_task):
        mock_transaction.on_commit = lambda func: func()

        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        mock_task.delay.assert_called_once_with(vote.id)

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.vote_signals.transaction")
    def test_signal_skips_on_downvote_creation(self, mock_transaction, mock_task):
        mock_transaction.on_commit = lambda func: func()

        Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.DOWNVOTE,
        )

        mock_task.delay.assert_not_called()

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.vote_signals.transaction")
    def test_signal_skips_on_vote_update(self, mock_transaction, mock_task):
        mock_transaction.on_commit = lambda func: func()

        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.DOWNVOTE,
        )

        mock_task.reset_mock()

        vote.vote_type = Vote.UPVOTE
        vote.save()

        mock_task.delay.assert_not_called()
