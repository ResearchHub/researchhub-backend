"""
Unit tests for hot_score_utils.py helper functions.

These tests validate the JSON extraction and calculation logic
using mock data without requiring database access.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from django.test import TestCase

from feed.hot_score_utils import (
    get_age_hours_from_content,
    get_bounties_from_content,
    get_comment_count_from_metrics,
    get_content_type_name,
    get_fundraise_amount_from_content,
    get_peer_review_count_from_metrics,
    get_tips_from_content,
    get_upvotes_rolled_up,
    get_votes_from_metrics,
    has_comments,
    parse_iso_datetime,
    safe_get_nested,
)


class TestHotScoreUtils(TestCase):
    """Test suite for hot score utility functions."""

    # ========================================================================
    # Core Helper Functions
    # ========================================================================

    def test_safe_get_nested(self):
        """Test safely navigating nested dictionaries."""
        data = {"a": {"b": {"c": 42}}}

        # Test successful navigation
        result = safe_get_nested(data, "a", "b", "c")
        self.assertEqual(result, 42)

        # Test with missing key returns default
        result = safe_get_nested(data, "a", "x", "y", default=0)
        self.assertEqual(result, 0)

    def test_has_comments(self):
        """Test checking if feed entry has comments."""
        # Test with replies > 0
        metrics = {"replies": 3, "review_metrics": {"count": 0}}
        self.assertTrue(has_comments(metrics))

        # Test with review_metrics.count > 0
        metrics = {"replies": 0, "review_metrics": {"count": 2}}
        self.assertTrue(has_comments(metrics))

        # Test with both = 0
        metrics = {"replies": 0, "review_metrics": {"count": 0}}
        self.assertFalse(has_comments(metrics))

    def test_get_content_type_name(self):
        """Test extracting content type name from feed entry."""
        # Mock feed_entry with content_type
        feed_entry = Mock()
        feed_entry.content_type.model = "paper"

        result = get_content_type_name(feed_entry)
        self.assertEqual(result, "paper")

    def test_parse_iso_datetime(self):
        """Test parsing ISO 8601 datetime strings."""
        # Test with Z suffix
        date_string = "2025-10-16T18:06:10.013228Z"
        result = parse_iso_datetime(date_string)

        self.assertIsInstance(result, datetime)
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 10)

    # ========================================================================
    # Metrics Extraction Functions
    # ========================================================================

    def test_get_votes_from_metrics(self):
        """Test extracting vote count from metrics JSON."""
        metrics = {"votes": 5, "replies": 0}

        result = get_votes_from_metrics(metrics)

        self.assertEqual(result, 5)
        self.assertIsInstance(result, int)

    def test_get_peer_review_count_from_metrics(self):
        """Test extracting peer review count from metrics JSON."""
        metrics = {"votes": 0, "replies": 0, "review_metrics": {"avg": 4.5, "count": 2}}

        result = get_peer_review_count_from_metrics(metrics)

        self.assertEqual(result, 2)
        self.assertIsInstance(result, int)

    def test_get_comment_count_from_metrics(self):
        """Test extracting comment count (excluding peer reviews)."""
        metrics = {"replies": 5, "review_metrics": {"count": 2}}

        result = get_comment_count_from_metrics(metrics)

        # Should return 5 - 2 = 3
        self.assertEqual(result, 3)
        self.assertIsInstance(result, int)

    # ========================================================================
    # Complex Extraction Functions
    # ========================================================================

    def test_get_bounties_from_content(self):
        """Test extracting bounty amount and urgency from content JSON."""
        content = {
            "bounties": [
                {
                    "id": 229,
                    "amount": "429.0000000000",
                    "status": "OPEN",
                    "expiration_date": "2025-10-20T20:47:34.373000Z",
                }
            ]
        }

        # Mock feed_entry with created_date
        feed_entry = Mock()
        feed_entry.created_date = datetime.now(timezone.utc)

        total_amount, has_urgent = get_bounties_from_content(content, feed_entry)

        self.assertEqual(total_amount, 429.0)
        self.assertIsInstance(total_amount, float)
        self.assertIsInstance(has_urgent, bool)

    def test_get_tips_from_content(self):
        """Test extracting tip amount from content JSON."""
        content = {
            "purchases": [{"id": 93, "amount": "50"}, {"id": 94, "amount": "25"}]
        }

        # Mock feed_entry with no comments
        feed_entry = Mock()
        feed_entry.metrics = {"replies": 0, "review_metrics": {"count": 0}}

        result = get_tips_from_content(content, feed_entry)

        # Should return 50 + 25 = 75
        self.assertEqual(result, 75.0)
        self.assertIsInstance(result, float)

    def test_get_upvotes_rolled_up(self):
        """Test extracting upvote count from metrics."""
        metrics = {"votes": 5, "replies": 0}

        # Mock feed_entry with no comments
        feed_entry = Mock()

        result = get_upvotes_rolled_up(metrics, feed_entry)

        self.assertEqual(result, 5)
        self.assertIsInstance(result, int)

    def test_get_fundraise_amount_from_content(self):
        """Test extracting fundraise amount (prefers RSC over USD)."""
        # Test with RSC
        content = {"fundraise": {"amount_raised": {"rsc": 150.5, "usd": 50}}}

        result = get_fundraise_amount_from_content(content)

        # Should prefer RSC over USD
        self.assertEqual(result, 150.5)
        self.assertIsInstance(result, float)

        # Test with USD fallback
        content = {"fundraise": {"amount_raised": {"usd": 50}}}

        result = get_fundraise_amount_from_content(content)
        self.assertEqual(result, 50.0)

    def test_get_age_hours_from_content(self):
        """Test calculating age in hours from content JSON."""
        # Create a date 24 hours ago
        created_date = datetime.now(timezone.utc) - timedelta(hours=24)
        content = {"created_date": created_date.isoformat()}

        # Mock feed_entry
        feed_entry = Mock()
        feed_entry.created_date = created_date

        result = get_age_hours_from_content(content, feed_entry)

        # Should be approximately 24 hours
        self.assertGreater(result, 23.9)
        self.assertLess(result, 24.1)
        self.assertIsInstance(result, float)
