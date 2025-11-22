from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from discussion.models import Vote
from paper.models import Paper
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from user.tests.helpers import create_random_default_user


class PaperSignalTests(TestCase):
    @patch("personalize.signals.paper_signals.sync_paper_to_personalize_task")
    def test_signal_queues_task_on_paper_creation(self, mock_task):
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        paper = Paper.objects.create(
            title="New Test Paper",
            paper_title="New Test Paper",
            unified_document=unified_doc,
            external_source="test",
        )

        mock_task.delay.assert_called_once_with(paper.id)

    @patch("personalize.signals.paper_signals.sync_paper_to_personalize_task")
    def test_signal_skips_on_paper_update(self, mock_task):
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER", is_removed=False
        )

        paper = Paper.objects.create(
            title="Test Paper",
            paper_title="Test Paper",
            unified_document=unified_doc,
            external_source="test",
        )

        mock_task.reset_mock()

        paper.title = "Updated Title"
        paper.save()

        mock_task.delay.assert_not_called()

    @patch("personalize.signals.paper_signals.sync_paper_to_personalize_task")
    def test_signal_skips_paper_without_unified_doc(self, mock_task):
        Paper.objects.create(
            title="Paper Without Unified Doc",
            paper_title="Paper Without Unified Doc",
            external_source="test",
            unified_document=None,
        )

        mock_task.delay.assert_not_called()


class VoteSignalTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("vote_test_user")
        self.post = create_post(created_by=self.user)
        self.content_type = ContentType.objects.get_for_model(self.post)

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    def test_signal_queues_task_on_upvote_creation(self, mock_task):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        mock_task.delay.assert_called_once_with(vote.id)

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    def test_signal_skips_on_downvote_creation(self, mock_task):
        Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.DOWNVOTE,
        )

        mock_task.delay.assert_not_called()

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    def test_signal_skips_on_vote_update(self, mock_task):
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
