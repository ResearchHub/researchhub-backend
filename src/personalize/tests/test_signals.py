from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.models import Vote
from paper.models import Paper
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from user.tests.helpers import create_random_default_user


class UnifiedDocumentSignalTests(TestCase):
    """Tests for unified document creation triggering personalize sync."""

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_queues_task_on_unified_doc_creation(self, mock_task):
        """Creating a unified document should trigger sync."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        mock_task.delay.assert_called_once_with(unified_doc.id)

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_skips_on_unified_doc_update(self, mock_task):
        """Updating a unified document should not trigger sync."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        mock_task.reset_mock()

        unified_doc.score = 100
        unified_doc.save()

        mock_task.delay.assert_not_called()

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_triggers_when_paper_creates_unified_doc(self, mock_task):
        """When a paper is created, add_unified_doc signal creates unified_doc which triggers sync."""
        # Create paper without unified_doc - the add_unified_doc signal
        paper = Paper.objects.create(
            title="Paper That Gets Unified Doc",
            paper_title="Paper That Gets Unified Doc",
            external_source="test",
            unified_document=None,
        )

        # Refresh to get the unified_document created by the signal
        paper.refresh_from_db()

        # The signal should have been triggered when unified_doc was created
        self.assertIsNotNone(paper.unified_document)
        mock_task.delay.assert_called_with(paper.unified_document.id)

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_triggers_when_post_created(self, mock_task):
        """Creating a post triggers unified document sync."""
        user = create_random_default_user("post_signal_user")
        post = create_post(created_by=user)

        mock_task.delay.assert_called_with(post.unified_document.id)


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
