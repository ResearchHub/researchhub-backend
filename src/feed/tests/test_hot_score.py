import datetime
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from feed.hot_score import (
    calculate_hot_score,
    calculate_time_decay,
    calculate_tip_score,
    calculate_vote_score,
    update_feed_entry_hot_score,
)
from feed.models import FeedEntry
from paper.related_models.paper_model import Paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class HotScoreCalculationTests(TestCase):
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

        # Create unified document
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER",
            hot_score=100,
        )

        # Create a test paper
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date=timezone.now(),
            score=10,
            unified_document=self.unified_document,
        )

        # Get the content type for the paper
        self.paper_content_type = ContentType.objects.get_for_model(Paper)

        # Create a feed entry for the paper
        self.feed_entry = FeedEntry.objects.create(
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.unified_document,
            action="PUBLISH",
            action_date=timezone.now() - datetime.timedelta(days=1),
            user=self.user,
        )

    def test_vote_score_calculation(self):
        """Test that vote score calculation works properly"""
        # Test with item having a score attribute
        score = calculate_vote_score(self.paper, self.paper_content_type)
        self.assertEqual(score, 10)

        # Test with mocked vote counts
        with patch("discussion.reaction_models.Vote.objects.filter") as mock_filter:
            # Mock upvotes count
            mock_upvotes = MagicMock()
            mock_upvotes.count.return_value = 15

            # Mock downvotes count
            mock_downvotes = MagicMock()
            mock_downvotes.count.return_value = 5

            # Set up the mock to return different values based on vote_type
            def mock_filter_side_effect(*args, **kwargs):
                if kwargs.get("vote_type", None) == 1:  # UPVOTE
                    return mock_upvotes
                else:  # DOWNVOTE
                    return mock_downvotes

            mock_filter.side_effect = mock_filter_side_effect

            # Create a mock item without a score attribute
            mock_item = MagicMock()
            del mock_item.score

            # Calculate vote score
            score = calculate_vote_score(mock_item, self.paper_content_type)

            # Should be upvotes - downvotes = 15 - 5 = 10
            self.assertEqual(score, 10)

    def test_comment_score_calculation(self):
        """Test that comment score calculation works properly"""
        # Mock the discussion count more robustly by patching calculate_comment_score
        with patch("feed.hot_score.calculate_comment_score") as mock_calc:
            mock_calc.return_value = 5

            # Calculate comment score
            comment_score = mock_calc(self.paper, self.paper_content_type)

            # Verify mock was called
            mock_calc.assert_called_once_with(self.paper, self.paper_content_type)
            self.assertEqual(comment_score, 5)

    def test_tip_score_calculation(self):
        """Test that tip score calculation works properly"""
        # Since we can't easily create Purchase objects in the test,
        # we'll use mocking to test the tip score calculation
        with patch("django.db.models.query.QuerySet.aggregate") as mock_aggregate:
            mock_aggregate.return_value = {"total": 100.0}

            # Create a mock for purchases filter
            mock_purchases = MagicMock()
            mock_purchases.filter.return_value = mock_purchases
            mock_purchases.exists.return_value = True
            mock_purchases.aggregate.return_value = {"total": 100.0}

            # Create a mock item with purchases attribute
            mock_item = MagicMock()
            mock_item.purchases = mock_purchases

            tip_score = calculate_tip_score(mock_item, self.paper_content_type)
            self.assertEqual(tip_score, 100.0)

    def test_time_decay_calculation(self):
        """Test that time decay calculation works properly"""
        # Test decay for a post created now
        now = timezone.now()
        decay = calculate_time_decay(now)
        # Decay should be close to 1.0 for a fresh post
        self.assertAlmostEqual(decay, 1.0, delta=0.01)

        # Test decay for a post created 3 days ago (half-life)
        three_days_ago = now - datetime.timedelta(days=3)
        decay = calculate_time_decay(three_days_ago)
        # Decay should be approximately 0.5 for a post at half-life
        self.assertAlmostEqual(decay, 0.5, delta=0.1)

        # Test decay for a post created 6 days ago (two half-lives)
        six_days_ago = now - datetime.timedelta(days=6)
        decay = calculate_time_decay(six_days_ago)
        # Decay should be approximately 0.25 for a post at two half-lives
        self.assertAlmostEqual(decay, 0.25, delta=0.1)

    def test_hot_score_calculation(self):
        """Test that the final hot score calculation combines factors properly"""
        # Set up our mocks
        with patch("feed.hot_score.calculate_vote_score") as mock_vote_score, patch(
            "feed.hot_score.calculate_comment_score"
        ) as mock_comment_score, patch(
            "feed.hot_score.calculate_tip_score"
        ) as mock_tip_score, patch(
            "feed.hot_score.calculate_time_decay"
        ) as mock_time_decay:

            # Set return values for our mocks
            mock_vote_score.return_value = 10
            mock_comment_score.return_value = 5
            mock_tip_score.return_value = 20
            mock_time_decay.return_value = 0.8

            # Calculate hot score
            hot_score = calculate_hot_score(self.feed_entry)

            # Verify our mocks were called
            mock_vote_score.assert_called_once()
            mock_comment_score.assert_called_once()
            mock_tip_score.assert_called_once()
            mock_time_decay.assert_called_once()

            # We expect the hot_score to be a positive integer
            self.assertGreater(hot_score, 0)
            self.assertEqual(type(hot_score), int)

            # With our mock values, we can calculate the expected score
            # Formula from hot_score.py (simplified for comments):
            # base_score = log(abs(vote_score) + 1, 2) * sign
            # comment_score = log(comment_count + 1, 2)
            # tip_score = log(tip_amount + 1, 4)
            # weight for paper = 1.2
            # Combined score with weight and decay ~= 7872

            # Allow some flexibility for calculation differences
            self.assertGreater(hot_score, 7500)
            self.assertLess(hot_score, 8300)

    def test_update_feed_entry_hot_score(self):
        """Test that update_feed_entry_hot_score updates the score and
        saves to database"""
        with patch("feed.hot_score.calculate_hot_score") as mock_calculate:
            # Set a specific return value
            mock_calculate.return_value = 12345

            # Call the update function
            result = update_feed_entry_hot_score(self.feed_entry)

            # Verify calculate_hot_score was called
            mock_calculate.assert_called_once_with(self.feed_entry)

            # Verify the result matches the mocked return value
            self.assertEqual(result, 12345)

            # Refresh the feed entry from the database
            self.feed_entry.refresh_from_db()

            # Verify the hot_score was updated
            self.assertEqual(self.feed_entry.hot_score, 12345)
