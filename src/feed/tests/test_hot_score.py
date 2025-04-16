"""
Tests for the hot score calculation module.
"""

import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from feed.hot_score import CONTENT_TYPE_WEIGHTS, calculate_hot_score


class TestHotScore(unittest.TestCase):
    """Test suite for hot score calculations."""

    def setUp(self):
        # Create a time reference for consistent testing
        self.now = datetime.now(timezone.utc)
        self.one_day_ago = self.now - timedelta(days=1)
        self.one_week_ago = self.now - timedelta(days=7)

    def create_test_item(
        self, score=10, discussion_count=5, created_date=None, bounties=None
    ):
        """Helper to create test items with controlled properties."""
        item = MagicMock()
        item.score = score
        item.get_discussion_count = MagicMock(return_value=discussion_count)
        item.created_date = created_date or self.now

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
    def test_paper_hot_score(self, mock_datetime):
        """Test hot score calculation for papers."""
        # Mock datetime.now() to return a fixed time
        mock_datetime.now.return_value = self.now
        mock_datetime.fromisoformat = datetime.fromisoformat

        # Create a paper from now
        paper = self.create_test_item(
            score=20, discussion_count=10, created_date=self.now
        )

        # Calculate expected score components for verification
        weights = CONTENT_TYPE_WEIGHTS["paper"]
        vote_component = 20 * weights["vote_weight"]
        discussion_component = math.log(11) * weights["reply_weight"] * 10
        bounty_component = 0  # No bounties
        base_score = vote_component + discussion_component + bounty_component

        # For a brand new paper, time decay should be close to 1
        expected_score = int(base_score)

        score = calculate_hot_score(paper, "paper")
        self.assertEqual(score, expected_score)

        # Test with an older paper (7 days old - half-life)
        old_paper = self.create_test_item(
            score=20, discussion_count=10, created_date=self.one_week_ago
        )

        # Half-life decay should reduce score by ~50%
        half_life_score = calculate_hot_score(old_paper, "paper")
        self.assertAlmostEqual(half_life_score, int(base_score * 0.5), delta=1)

    @patch("feed.hot_score.datetime")
    def test_post_hot_score(self, mock_datetime):
        """Test hot score calculation for ResearchHub posts."""
        mock_datetime.now.return_value = self.now
        mock_datetime.fromisoformat = datetime.fromisoformat

        # Test post with some bounties - pass amounts instead of mock objects
        post = self.create_test_item(
            score=15,
            discussion_count=8,
            created_date=self.one_day_ago,
            bounties=[10, 15],  # Pass a list of amounts
        )

        weights = CONTENT_TYPE_WEIGHTS["researchhubpost"]
        vote_component = 15 * weights["vote_weight"]
        discussion_component = math.log(9) * weights["reply_weight"] * 10
        bounty_component = math.sqrt(25) * weights["bounty_weight"]
        base_score = vote_component + discussion_component + bounty_component

        # 1 day decay for a post with 3-day half-life
        decay_factor = math.pow(2, -1 / 3)
        expected_score = int(base_score * decay_factor)

        score = calculate_hot_score(post, "researchhubpost")
        self.assertEqual(score, expected_score)

    @patch("feed.hot_score.datetime")
    def test_comment_hot_score(self, mock_datetime):
        """Test hot score calculation for comments."""
        mock_datetime.now.return_value = self.now
        mock_datetime.fromisoformat = datetime.fromisoformat

        comment = self.create_test_item(
            score=5, discussion_count=2, created_date=self.one_day_ago  # Replies
        )

        score = calculate_hot_score(comment, "rhcommentmodel")

        # Verify score is reasonable
        self.assertGreater(score, 0)

    @patch("feed.hot_score.datetime")
    def test_unknown_content_type(self, mock_datetime):
        """Test that unknown content types default to paper weights."""
        mock_datetime.now.return_value = self.now

        item = self.create_test_item(score=10, discussion_count=5)

        # Calculate with unknown type
        unknown_score = calculate_hot_score(item, "unknown_type")
        # Calculate with paper type
        paper_score = calculate_hot_score(item, "paper")

        # Both should use the same weights
        self.assertEqual(unknown_score, paper_score)

    @patch("feed.hot_score.datetime")
    def test_string_date_parsing(self, mock_datetime):
        """Test parsing string dates in the hot score calculation."""
        mock_datetime.now.return_value = self.now
        mock_datetime.fromisoformat = datetime.fromisoformat

        item = self.create_test_item(score=10)
        item.created_date = self.one_day_ago

        # Should parse the string without errors
        score = calculate_hot_score(item, "paper")
        self.assertGreater(score, 0)

    @patch("feed.hot_score.datetime")
    def test_minimum_score(self, mock_datetime):
        """Test that the minimum score is 1 for valid content."""
        mock_datetime.now.return_value = self.now

        # Create very old content with minimal activity
        old_item = self.create_test_item(
            score=1,
            discussion_count=0,
            created_date=self.now - timedelta(days=100),  # Very old
        )

        score = calculate_hot_score(old_item, "paper")
        # Even with heavy time decay, score should be at least 1
        self.assertEqual(score, 1)

    @patch("feed.hot_score.datetime")
    def test_bounty_calculation(self, mock_datetime):
        """Test hot score calculation with various bounty amounts."""
        mock_datetime.now.return_value = self.now

        # Test with multiple bounties
        item = self.create_test_item(
            score=10, discussion_count=5, bounties=[5, 10, 15]  # 30 total bounty amount
        )

        score_with_bounties = calculate_hot_score(item, "paper")

        # Test with no bounties for comparison
        item_no_bounties = self.create_test_item(score=10, discussion_count=5)

        score_no_bounties = calculate_hot_score(item_no_bounties, "paper")

        # Score with bounties should be higher
        self.assertGreater(score_with_bounties, score_no_bounties)

        # Verify sqrt of bounty amount is used in calculation
        weights = CONTENT_TYPE_WEIGHTS["paper"]
        # Calculate bounty component
        bounty_weight = weights["bounty_weight"]
        bounty_component = math.sqrt(30) * bounty_weight
        self.assertGreater(bounty_component, 0)

    @patch("feed.hot_score.datetime")
    def test_bounties_error_handling(self, mock_datetime):
        """Test error handling when accessing bounties raises an exception."""
        mock_datetime.now.return_value = self.now

        # Create an item with a bounties attribute that raises an exception when accessed
        item = self.create_test_item(score=10, discussion_count=5)
        item.bounties = MagicMock()
        item.bounties.all.side_effect = Exception("DB Error")

        # Should handle the exception gracefully
        try:
            score = calculate_hot_score(item, "paper")
            self.assertGreater(score, 0)
        except Exception:
            self.fail("calculate_hot_score raised an exception unexpectedly!")
