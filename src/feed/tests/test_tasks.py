from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.tasks import (
    _get_unified_document,
    create_feed_entry,
    delete_feed_entry,
    refresh_feed_entries_for_objects,
    update_feed_metrics,
)
from hub.models import Hub
from paper.models import Paper
from reputation.related_models.bounty import Bounty
from reputation.related_models.escrow import Escrow
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User
from user.related_models.author_model import Author


class FeedTasksTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testUser1")

        self.unified_document = ResearchhubUnifiedDocument.objects.create()
        self.paper = Paper.objects.create(
            title="testPaper1",
            paper_publish_date="2025-01-01",
            unified_document=self.unified_document,
        )
        self.hub = Hub.objects.create(name="testHub1")

        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.hub_content_type = ContentType.objects.get_for_model(Hub)

    def test_create_feed_entry(self):
        """Test creating a feed entry for a paper."""
        # Act
        create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Assert
        feed_entry = FeedEntry.objects.get(
            object_id=self.paper.id, content_type=self.paper_content_type
        )

        self.assertEqual(feed_entry.user, self.user)
        self.assertEqual(feed_entry.action, FeedEntry.PUBLISH)
        self.assertEqual(feed_entry.item, self.paper)
        self.assertEqual(feed_entry.hubs.first(), self.hub)
        self.assertEqual(feed_entry.unified_document, self.paper.unified_document)

    def test_create_feed_entry_twice(self):
        """Test that attempting to create the same feed entry twice
        doesn't raise an error.
        """
        # Act
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
        )
        # attempt to create the same feed entry again
        create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
        )

        # Assert
        feed_entries = FeedEntry.objects.filter(id=feed_entry.id)
        self.assertEqual(feed_entries.count(), 1)

    def test_delete_feed_entry(self):
        """Test deleting a feed entry for a paper"""
        # Arrange
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Act
        delete_feed_entry(
            item_id=feed_entry.item.id,
            item_content_type_id=feed_entry.content_type.id,
            hub_ids=[self.hub.id],
        )

        # Assert
        self.assertFalse(FeedEntry.objects.filter(id=feed_entry.id).exists())

    def test_delete_feed_entry_which_does_not_exist(self):
        """Test attempting to delete a feed entry that doesn't exist"""
        try:
            delete_feed_entry(
                item_id=self.paper.id,
                item_content_type_id=self.paper_content_type.id,
                hub_ids=[self.hub.id],
            )
        except Exception as e:
            self.fail(f"delete_feed_entry raised an exception: {e}")

    def test_get_unified_document_for_paper(self):
        """
        Test getting a unified document from a paper.
        """
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create()
        paper = Paper.objects.create(title="paper1", unified_document=unified_document)
        content_type = ContentType.objects.get_for_model(Paper)

        # Act
        actual = _get_unified_document(paper, content_type)

        # Assert
        self.assertEqual(actual, paper.unified_document)

    def test_get_unified_document_for_bounty(self):
        """
        Test getting a unified document from a bounty.
        """
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create()
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            item=self.paper.unified_document,
        )
        bounty = Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            item=self.paper,
            unified_document=unified_document,
        )
        content_type = ContentType.objects.get_for_model(Bounty)

        # Act
        actual = _get_unified_document(bounty, content_type)

        # Assert
        self.assertEqual(actual, bounty.unified_document)

    def test_get_unified_document_for_comment(self):
        """Test getting a unified document from a comment."""
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create()
        paper = Paper.objects.create(title="paper1", unified_document=unified_document)
        thread = RhCommentThreadModel.objects.create(
            content_type=self.paper_content_type,
            object_id=paper.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(thread=thread, created_by=self.user)
        content_type = ContentType.objects.get_for_model(RhCommentModel)

        # Act
        actual = _get_unified_document(comment, content_type)

        # Assert
        self.assertEqual(actual, comment.thread.unified_document)

    def test_get_unified_document_for_post(self):
        """Test getting a unified document from a post."""
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create()
        post = ResearchhubPost.objects.create(
            unified_document=unified_document, created_by=self.user
        )
        content_type = ContentType.objects.get_for_model(ResearchhubPost)

        # Act
        actual = _get_unified_document(post, content_type)

        # Assert
        self.assertEqual(actual, post.unified_document)

    def test_update_feed_metrics(self):
        """Test updating feed metrics for a paper."""
        # Arrange
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Create mock review metrics
        review_metrics = {"avg": 4.7, "count": 5}

        # Act
        with patch.object(
            self.paper.unified_document,
            "get_review_details",
            return_value=review_metrics,
        ):
            update_feed_metrics(
                item_id=self.paper.id,
                item_content_type_id=self.paper_content_type.id,
                metrics={"votes": 10, "review_metrics": review_metrics},
            )

            # Assert
            feed_entry = FeedEntry.objects.get(id=feed_entry.id)
            self.assertEqual(feed_entry.metrics["votes"], 10)
            self.assertIn("review_metrics", feed_entry.metrics)
            self.assertEqual(feed_entry.metrics["review_metrics"], review_metrics)

    def test_update_feed_metrics_feed_entry_does_not_exist(self):
        """Test updating feed metrics for a feed entry that doesn't exist."""
        # Act
        update_feed_metrics(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            metrics={"votes": 10},
        )

        # Assert
        self.assertFalse(FeedEntry.objects.filter(id=self.paper.id).exists())

    def test_refresh_feed_entries_for_objects(self):
        """Test refreshing feed entries for a paper."""
        # Arrange
        # Create a feed entry
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Store original content and metrics
        original_content = feed_entry.content.copy()
        original_metrics = feed_entry.metrics.copy()

        # Modify the paper
        self.paper.title = "Updated Test Paper"
        self.paper.save()

        # Act
        refresh_feed_entries_for_objects(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
        )

        # Assert
        # Fetch the updated feed entry
        updated_feed_entry = FeedEntry.objects.get(id=feed_entry.id)

        # Verify content was updated
        self.assertNotEqual(updated_feed_entry.content, original_content)
        self.assertEqual(updated_feed_entry.content["title"], "Updated Test Paper")

        # Verify metrics still exist
        self.assertEqual(
            set(updated_feed_entry.metrics.keys()), set(original_metrics.keys())
        )

    def test_refresh_feed_hot_scores(self):
        """Test refreshing hot scores for feed entries using actual database entries."""
        # Arrange
        from feed.tasks import refresh_feed_hot_scores

        # Create 3 feed entries with different properties
        papers = []
        feed_entries = []

        # Create 3 papers with different properties
        for i in range(3):
            # Create a unified document for each paper
            unified_doc = ResearchhubUnifiedDocument.objects.create()

            # Create a paper with different creation dates to affect hot score
            paper = Paper.objects.create(
                title=f"Test Paper {i+1}",
                paper_publish_date="2025-01-01",
                unified_document=unified_doc,
                score=10 * (i + 1),  # Different scores to get different hot scores
            )
            papers.append(paper)

            # Create a feed entry for each paper
            feed_entry = create_feed_entry(
                item_id=paper.id,
                item_content_type_id=self.paper_content_type.id,
                action=FeedEntry.PUBLISH,
                hub_ids=[self.hub.id],
                user_id=self.user.id,
            )
            feed_entries.append(feed_entry)

        # Verify that the entries were created
        self.assertGreaterEqual(len(feed_entries), 3)

        # Record initial hot scores
        initial_hot_scores = {}
        for entry in feed_entries:
            initial_hot_scores[entry.id] = entry.hot_score_v2

        # Act
        refresh_feed_hot_scores()

        # Assert
        # Fetch updated feed entries
        updated_feed_entries = []
        for entry_id in [entry.id for entry in feed_entries]:
            updated_entry = FeedEntry.objects.get(id=entry_id)
            updated_feed_entries.append(updated_entry)

        # Verify that hot scores have been updated if they are greater than 10
        for i, entry in enumerate(updated_feed_entries):
            # Hot scores should be updated and different from initial values
            if initial_hot_scores[entry.id] and initial_hot_scores[entry.id] > 10:
                self.assertNotEqual(
                    entry.hot_score_v2,
                    initial_hot_scores[entry.id],
                    f"Hot score for entry {i} was not updated",
                )

    def test_create_feed_entry_populates_authors_for_paper(self):
        """Test that creating a feed entry for a paper populates the authors field."""
        # Arrange
        author1 = Author.objects.create(first_name="John", last_name="Doe")
        author2 = Author.objects.create(first_name="Jane", last_name="Smith")
        self.paper.authors.add(author1, author2)

        # Act
        create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Assert
        feed_entry = FeedEntry.objects.get(
            object_id=self.paper.id, content_type=self.paper_content_type
        )
        self.assertEqual(feed_entry.authors.count(), 2)
        self.assertIn(author1, feed_entry.authors.all())
        self.assertIn(author2, feed_entry.authors.all())

    def test_create_feed_entry_populates_authors_for_post(self):
        """Test that creating a feed entry for a post populates the authors field."""
        # Arrange
        user = User.objects.create(username="postauthor2")
        author1 = Author.objects.create(first_name="Post", last_name="Author")
        unified_document = ResearchhubUnifiedDocument.objects.create()
        post = ResearchhubPost.objects.create(
            unified_document=unified_document, created_by=user
        )
        post.authors.add(author1)
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        # Act
        create_feed_entry(
            item_id=post.id,
            item_content_type_id=post_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=user.id,
        )

        # Assert
        feed_entry = FeedEntry.objects.get(
            object_id=post.id, content_type=post_content_type
        )
        self.assertEqual(feed_entry.authors.count(), 1)
        self.assertEqual(feed_entry.authors.first(), author1)

    def test_refresh_feed_entries_updates_authors(self):
        """Test that refreshing feed entries updates the authors field."""
        # Arrange
        author1 = Author.objects.create(first_name="John", last_name="Doe")
        self.paper.authors.add(author1)

        # Create feed entry
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Verify initial authors
        self.assertEqual(feed_entry.authors.count(), 1)
        self.assertIn(author1, feed_entry.authors.all())

        # Add another author to the paper
        author2 = Author.objects.create(first_name="Jane", last_name="Smith")
        self.paper.authors.add(author2)

        # Act
        refresh_feed_entries_for_objects(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
        )

        # Assert
        updated_feed_entry = FeedEntry.objects.get(id=feed_entry.id)
        self.assertEqual(updated_feed_entry.authors.count(), 2)
        self.assertIn(author1, updated_feed_entry.authors.all())
        self.assertIn(author2, updated_feed_entry.authors.all())

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    @patch("feed.models.FeedEntry.calculate_hot_score_v2")
    def test_refresh_feed_entry_triggers_figure_extraction_for_paper(
        self, mock_calculate, mock_trigger
    ):
        """Test refresh_feed_entry calls trigger for papers."""
        from feed.tasks import refresh_feed_entry

        # Create a feed entry
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Mock calculate_hot_score_v2 to return a high score
        mock_calculate.return_value = 100

        # Act
        refresh_feed_entry(feed_entry.id)

        # Assert - check it was called with the mocked hot_score_v2 value
        mock_trigger.assert_called_once_with(self.paper.id, 100)

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    def test_refresh_feed_entry_does_not_trigger_for_non_paper(self, mock_trigger):
        """Test refresh_feed_entry doesn't call trigger for non-paper content types."""
        from feed.tasks import refresh_feed_entry

        # Create a post
        unified_doc = ResearchhubUnifiedDocument.objects.create()
        post = ResearchhubPost.objects.create(
            unified_document=unified_doc, created_by=self.user
        )
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        # Create feed entry for post
        feed_entry = create_feed_entry(
            item_id=post.id,
            item_content_type_id=post_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Act
        refresh_feed_entry(feed_entry.id)

        # Assert
        mock_trigger.assert_not_called()

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    @patch("feed.models.FeedEntry.calculate_hot_score_v2")
    def test_refresh_feed_entries_for_objects_triggers_figure_extraction(
        self, mock_calculate, mock_trigger
    ):
        """Test function calls trigger when skip_figure_extraction=False."""
        # Create a feed entry
        create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Mock calculate_hot_score_v2 to return a high score
        mock_calculate.return_value = 100

        # Act
        refresh_feed_entries_for_objects(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            skip_figure_extraction=False,
        )

        # Assert - check it was called with the mocked hot_score_v2 value
        mock_trigger.assert_called_once_with(self.paper.id, 100)

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    def test_refresh_feed_entries_for_objects_skips_figure_extraction(
        self, mock_trigger
    ):
        """Test that function doesn't call trigger when skip_figure_extraction=True."""
        # Create a feed entry
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Set a high hot_score_v2
        feed_entry.hot_score_v2 = 100
        feed_entry.save()

        # Act
        refresh_feed_entries_for_objects(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            skip_figure_extraction=True,
        )

        # Assert
        mock_trigger.assert_not_called()

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    def test_refresh_feed_entries_for_objects_only_triggers_once_per_paper(
        self, mock_trigger
    ):
        """Test that checked_figure_extraction flag prevents multiple calls."""
        # Create multiple feed entries for the same paper (different hubs)
        hub2 = Hub.objects.create(name="testHub2")
        feed_entry1 = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )
        feed_entry2 = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[hub2.id],
            user_id=self.user.id,
        )

        # Set high hot_score_v2 for both
        feed_entry1.hot_score_v2 = 100
        feed_entry1.save()
        feed_entry2.hot_score_v2 = 100
        feed_entry2.save()

        # Act
        refresh_feed_entries_for_objects(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            skip_figure_extraction=False,
        )

        # Assert - should only be called once despite multiple feed entries
        self.assertEqual(mock_trigger.call_count, 1)

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    def test_refresh_feed_entries_for_objects_does_not_trigger_for_non_paper(
        self, mock_trigger
    ):
        """Test that function doesn't call trigger for non-paper content types."""
        # Create a post
        unified_doc = ResearchhubUnifiedDocument.objects.create()
        post = ResearchhubPost.objects.create(
            unified_document=unified_doc, created_by=self.user
        )
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        # Create feed entry for post
        create_feed_entry(
            item_id=post.id,
            item_content_type_id=post_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )

        # Act
        refresh_feed_entries_for_objects(
            item_id=post.id,
            item_content_type_id=post_content_type.id,
            skip_figure_extraction=False,
        )

        # Assert
        mock_trigger.assert_not_called()

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    def test_refresh_feed_hot_scores_batch_triggers_figure_extraction(
        self, mock_trigger
    ):
        """Test batch refresh calls trigger_figure_extraction_for_paper for papers."""
        from feed.tasks import refresh_feed_hot_scores_batch

        # Create feed entries with high scores
        papers = []
        feed_entries = []
        for i in range(2):
            unified_doc = ResearchhubUnifiedDocument.objects.create()
            paper = Paper.objects.create(
                title=f"Test Paper {i+1}",
                paper_publish_date="2025-01-01",
                unified_document=unified_doc,
                score=100,  # High score to get high hot_score_v2
            )
            papers.append(paper)

            feed_entry = create_feed_entry(
                item_id=paper.id,
                item_content_type_id=self.paper_content_type.id,
                action=FeedEntry.PUBLISH,
                hub_ids=[self.hub.id],
                user_id=self.user.id,
            )
            feed_entries.append(feed_entry)

        # Act
        refresh_feed_hot_scores_batch(
            queryset=FeedEntry.objects.filter(id__in=[e.id for e in feed_entries]),
            batch_size=1000,
        )

        # Assert - should be called for each paper
        self.assertEqual(mock_trigger.call_count, 2)

    @patch("feed.tasks.trigger_figure_extraction_for_paper")
    def test_refresh_feed_hot_scores_batch_uses_processed_papers_set(
        self, mock_trigger
    ):
        """Test that processed_papers set prevents duplicate calls."""
        from feed.tasks import refresh_feed_hot_scores_batch

        # Create multiple feed entries for the same paper
        hub2 = Hub.objects.create(name="testHub2")
        feed_entry1 = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[self.hub.id],
            user_id=self.user.id,
        )
        feed_entry2 = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            hub_ids=[hub2.id],
            user_id=self.user.id,
        )

        # Act
        refresh_feed_hot_scores_batch(
            queryset=FeedEntry.objects.filter(id__in=[feed_entry1.id, feed_entry2.id]),
            batch_size=1000,
        )

        # Assert - should only be called once per paper
        self.assertEqual(mock_trigger.call_count, 1)
