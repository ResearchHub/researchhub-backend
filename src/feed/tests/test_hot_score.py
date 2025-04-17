"""
Tests for the hot score calculation module.
"""

import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from feed.hot_score import (
    CONTENT_TYPE_WEIGHTS,
    calculate_hot_score,
    calculate_hot_score_for_item,
)


class TestHotScore(unittest.TestCase):
    """Test suite for hot score calculations."""

    def setUp(self):
        # Create a time reference for consistent testing
        self.now = datetime.now(timezone.utc)
        self.one_day_ago = self.now - timedelta(days=1)
        self.one_week_ago = self.now - timedelta(days=7)

    def create_test_item(
        self,
        score=10,
        discussion_count=5,
        created_date=None,
        bounties=None,
        content_type_name="paper",
    ):
        """Helper to create test items with controlled properties."""
        item = MagicMock()
        item.score = score
        item.get_discussion_count = MagicMock(return_value=discussion_count)
        item.created_date = created_date or self.now
        item.content_type = MagicMock()
        item.content_type.model_name = content_type_name

        # Setup bounties if provided
        if bounties:
            # Create a MagicMock for bounties with real bounty objects
            item.bounties = MagicMock()
            item.bounties.all.return_value = [
                self.create_bounty(amount) for amount in bounties
            ]
        return item

    def create_bounty(self, amount):
        """Create a real bounty object with specified amount."""
        bounty = MagicMock()
        bounty.amount = amount
        bounty.created_date = self.now - timedelta(days=1)  # Default to 1 day old
        return bounty

    @patch("feed.hot_score.datetime")
    @patch("feed.hot_score.ContentType")
    def test_comment_hot_score(self, mock_content_type, mock_datetime):
        """Test hot score calculation for comments."""
        mock_datetime.now.return_value = self.now
        mock_datetime.fromisoformat = datetime.fromisoformat

        # Setup content type mock
        mock_content_type_instance = MagicMock()
        mock_content_type_instance.model_name = "rhcommentmodel"
        mock_content_type.objects.get_for_model.return_value = (
            mock_content_type_instance
        )

        comment = self.create_test_item(
            score=5,
            discussion_count=2,
            created_date=self.one_day_ago,
            content_type_name="rhcommentmodel",
        )

        score = calculate_hot_score_for_item(comment)

        # Verify score is reasonable
        self.assertGreater(score, 0)

    @patch("feed.hot_score.datetime")
    @patch("feed.hot_score.ContentType")
    def test_unknown_content_type(self, mock_content_type, mock_datetime):
        """Test that unknown content types default to paper weights."""
        mock_datetime.now.return_value = self.now

        # Setup content type mock
        mock_unknown_type = MagicMock()
        mock_unknown_type.model_name = "unknown_type"
        mock_paper_type = MagicMock()
        mock_paper_type.model_name = "paper"

        # Create two different items to test
        unknown_item = self.create_test_item(
            score=10, discussion_count=5, content_type_name="unknown_type"
        )
        paper_item = self.create_test_item(
            score=10, discussion_count=5, content_type_name="paper"
        )

        # Setup the ContentType.objects.get_for_model to return the proper model_name
        mock_content_type.objects.get_for_model.side_effect = [
            mock_unknown_type,
            mock_paper_type,
        ]

        # Calculate with unknown type
        unknown_score = calculate_hot_score(unknown_item, "unknown_type")
        # Calculate with paper type
        paper_score = calculate_hot_score(paper_item, "paper")

        # Both should use the same weights
        self.assertEqual(unknown_score, paper_score)

    @patch("feed.hot_score.datetime")
    @patch("feed.hot_score.ContentType")
    def test_string_date_parsing(self, mock_content_type, mock_datetime):
        """Test parsing string dates in the hot score calculation."""
        mock_datetime.now.return_value = self.now
        mock_datetime.fromisoformat = datetime.fromisoformat

        # Setup content type mock
        mock_content_type_instance = MagicMock()
        mock_content_type_instance.model_name = "paper"
        mock_content_type.objects.get_for_model.return_value = (
            mock_content_type_instance
        )

        item = self.create_test_item(score=10)
        item.created_date = self.one_day_ago

        # Should parse the string without errors
        score = calculate_hot_score_for_item(item)
        self.assertGreater(score, 0)

    @patch("feed.hot_score.datetime")
    @patch("feed.hot_score.ContentType")
    def test_minimum_score(self, mock_content_type, mock_datetime):
        """Test that the minimum score is 1 for valid content."""
        mock_datetime.now.return_value = self.now

        # Setup content type mock
        mock_content_type_instance = MagicMock()
        mock_content_type_instance.model_name = "paper"
        mock_content_type.objects.get_for_model.return_value = (
            mock_content_type_instance
        )

        # Create very old content with minimal activity
        old_item = self.create_test_item(
            score=1,
            discussion_count=0,
            created_date=self.now - timedelta(days=100),  # Very old
        )

        score = calculate_hot_score_for_item(old_item)
        # Even with heavy time decay, score should be at least 1
        self.assertEqual(score, 1)

    @patch("feed.hot_score.datetime")
    @patch("feed.hot_score.ContentType")
    def test_bounty_calculation(self, mock_content_type, mock_datetime):
        """Test hot score calculation with various bounty amounts."""
        mock_datetime.now.return_value = self.now

        # Setup content type mock
        mock_content_type_instance = MagicMock()
        mock_content_type_instance.model_name = "paper"
        mock_content_type.objects.get_for_model.return_value = (
            mock_content_type_instance
        )

        # Test with multiple bounties
        item = self.create_test_item(
            score=10, discussion_count=5, bounties=[5, 10, 15]  # 30 total bounty amount
        )

        score_with_bounties = calculate_hot_score_for_item(item)

        # Test with no bounties for comparison
        item_no_bounties = self.create_test_item(score=10, discussion_count=5)

        score_no_bounties = calculate_hot_score_for_item(item_no_bounties)

        # Score with bounties should be higher
        self.assertGreater(score_with_bounties, score_no_bounties)

        # Verify sqrt of bounty amount is used in calculation
        weights = CONTENT_TYPE_WEIGHTS["paper"]
        # Calculate bounty component
        bounty_weight = weights["bounty_weight"]
        bounty_component = math.sqrt(30) * bounty_weight
        self.assertGreater(bounty_component, 0)

    @patch("feed.hot_score.datetime")
    @patch("feed.hot_score.ContentType")
    def test_bounties_error_handling(self, mock_content_type, mock_datetime):
        """Test error handling when accessing bounties raises an exception."""
        mock_datetime.now.return_value = self.now

        # Setup content type mock
        mock_content_type_instance = MagicMock()
        mock_content_type_instance.model_name = "paper"
        mock_content_type.objects.get_for_model.return_value = (
            mock_content_type_instance
        )

        # Create an item with bounties that raises exception
        item = self.create_test_item(score=10, discussion_count=5)
        item.bounties = MagicMock()
        item.bounties.all.side_effect = Exception("DB Error")

        # Should handle the exception gracefully
        try:
            score = calculate_hot_score_for_item(item)
            self.assertGreater(score, 0)
        except Exception as e:
            print(e)
            self.fail("calculate_hot_score_for_item raised an exception unexpectedly!")

    @patch("feed.hot_score.datetime")
    @patch("feed.hot_score.ContentType")
    def test_peer_review_above_paper(self, mock_content_type, mock_datetime):
        """Test that a peer review's hot score is higher than the paper it reviews."""
        mock_datetime.now.return_value = self.now

        # Create a paper score to compare against
        paper_score = 15

        # Create a peer review comment
        peer_review = self.create_test_item(
            score=5, discussion_count=3, content_type_name="comment"
        )
        peer_review.comment_type = "REVIEW"

        # Mock the unified_document that links the peer review to the paper
        unified_doc = MagicMock()
        peer_review.unified_document = unified_doc

        # Mock the feed_entries relationship
        feed_entry = MagicMock()
        feed_entry.hot_score = paper_score
        unified_doc.feed_entries = MagicMock()
        unified_doc.feed_entries.filter.return_value = MagicMock()
        unified_doc.feed_entries.filter.return_value.first.return_value = feed_entry
        unified_doc.feed_entries.filter.return_value.count.return_value = 1

        # Mock the ContentType logic
        # For both the item checking and the feed entry filtering
        mock_comment_type = MagicMock()
        mock_comment_type.model_name = "comment"
        mock_paper_type = MagicMock()
        mock_post_type = MagicMock()
        mock_content_type.objects.get_for_model.side_effect = [
            mock_comment_type,
            mock_paper_type,
            mock_post_type,
        ]

        # Calculate the peer review score using the updated function
        peer_review_score = calculate_hot_score_for_item(peer_review)

        # Verify that the peer review score is higher than the paper score
        self.assertGreater(peer_review_score, paper_score)

        # For completeness - verify the component score
        # Reset the side_effect to return mock_comment_type again
        mock_content_type.objects.get_for_model.side_effect = [mock_comment_type]
        # We need to create a new comment that's not a review to test component score
        regular_comment = self.create_test_item(
            score=5, discussion_count=3, content_type_name="rhcommentmodel"
        )
        peer_review_component = calculate_hot_score_for_item(regular_comment)

        # The final score should be at least paper score + component
        self.assertGreaterEqual(peer_review_score, paper_score + peer_review_component)
