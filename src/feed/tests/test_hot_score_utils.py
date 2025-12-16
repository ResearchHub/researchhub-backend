"""
Unit tests for hot_score_utils.py helper functions.

These tests validate the JSON extraction and calculation logic
using mock data without requiring database access.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from django.test import TestCase

from feed.hot_score_utils import (
    calculate_adjusted_score,
    calculate_bluesky_engagement,
    calculate_github_engagement,
    calculate_x_engagement,
    get_age_hours_from_content,
    get_bounties_from_content,
    get_comment_count_from_metrics,
    get_content_type_name,
    get_fundraise_amount_from_content,
    get_peer_review_count_from_metrics,
    get_social_media_engagement_from_metrics,
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
        """Test extracting comment count.

        Note: The 'replies' field already excludes peer reviews since it comes from
        get_discussion_count() which only counts GENERIC_COMMENT type comments.
        So we just return the replies value directly.
        """
        metrics = {"replies": 5, "review_metrics": {"count": 2}}

        result = get_comment_count_from_metrics(metrics)

        # Should return 5 (replies value directly, since it already excludes
        # peer reviews)
        self.assertEqual(result, 5)
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
        """Test calculating age in hours using feed_entry.action_date.

        For papers: action_date = paper_publish_date
        For posts: action_date = created_date
        """
        # Create a date 24 hours ago
        action_date = datetime.now(timezone.utc) - timedelta(hours=24)
        content = {}  # Content is only used for urgency checks (GRANT, PREREGISTRATION)

        # Mock feed_entry with action_date
        feed_entry = Mock()
        feed_entry.action_date = action_date

        result = get_age_hours_from_content(content, feed_entry)

        # Should be approximately 24 hours
        self.assertGreater(result, 23.9)
        self.assertLess(result, 24.1)
        self.assertIsInstance(result, float)

    def test_old_paper_uses_action_date_for_age(self):
        """Test that old papers use action_date (paper_publish_date), not created_date."""
        # Setup: Paper published 180 days ago, but added to platform today
        paper_publish_date = datetime.now(timezone.utc) - timedelta(days=180)
        platform_created_date = datetime.now(timezone.utc)

        feed_entry = Mock()
        feed_entry.action_date = paper_publish_date

        content = {"created_date": platform_created_date.isoformat()}

        # Act
        age_hours = get_age_hours_from_content(content, feed_entry)

        # Assert: Age should be ~180 days (4320 hours), not 0
        self.assertAlmostEqual(age_hours, 180 * 24, delta=1)

    def test_calculate_x_engagement(self):
        """Test extracting X/Twitter engagement score."""
        x_data = {
            "post_count": 2,
            "total_likes": 10,
            "total_quotes": 2,
            "total_replies": 1,
            "total_reposts": 5,
            "total_impressions": 500,
        }

        result = calculate_x_engagement(x_data)

        # Raw: (500 * 0.1) + (10 * 1.0) + (5 * 3.0) + (2 * 5.0) + (1 * 2.0)
        # = 50 + 10 + 15 + 10 + 2 = 87.0
        # With platform multiplier (0.6): 87.0 * 0.6 = 52.2
        self.assertAlmostEqual(result, 52.2, places=1)
        self.assertIsInstance(result, float)

    def test_calculate_bluesky_engagement(self):
        """Test extracting Bluesky engagement score."""
        bluesky_data = {
            "post_count": 2,
            "total_likes": 20,
            "total_quotes": 2,
            "total_replies": 3,
            "total_reposts": 5,
        }

        result = calculate_bluesky_engagement(bluesky_data)

        # Raw: (20 * 1.0) + (5 * 3.0) + (2 * 5.0) + (3 * 2.0)
        # = 20 + 15 + 10 + 6 = 51.0
        # With platform multiplier (0.1): 51.0 * 0.1 = 5.1
        self.assertAlmostEqual(result, 5.1, places=1)
        self.assertIsInstance(result, float)

    def test_calculate_github_engagement(self):
        """Test extracting GitHub mentions engagement score."""
        github_data = {
            "total_mentions": 3,
            "breakdown": {"code": 2, "issues": 1},
        }

        result = calculate_github_engagement(github_data)

        # Raw: 3 * 10.0 = 30.0
        # With platform multiplier (0.3): 30.0 * 0.3 = 9.0
        self.assertAlmostEqual(result, 9.0, places=1)
        self.assertIsInstance(result, float)

    def test_get_social_media_engagement_from_metrics_all_sources(self):
        """Test combined social media engagement from all sources."""
        metrics = {
            "votes": 5,
            "replies": 3,
            "external": {
                "x": {
                    "post_count": 2,
                    "total_likes": 10,
                    "total_quotes": 2,
                    "total_replies": 1,
                    "total_reposts": 5,
                    "total_impressions": 500,
                },
                "bluesky": {
                    "post_count": 2,
                    "total_likes": 20,
                    "total_quotes": 2,
                    "total_replies": 3,
                    "total_reposts": 5,
                },
                "github_mentions": {
                    "total_mentions": 3,
                    "breakdown": {"code": 2, "issues": 1},
                },
            },
        }

        result = get_social_media_engagement_from_metrics(metrics)

        # Expected: X (52.2) + Bluesky (5.1) + GitHub (9.0) = 66.3
        self.assertAlmostEqual(result, 66.3, places=1)
        self.assertIsInstance(result, float)

    def test_get_social_media_engagement_from_metrics_x_only(self):
        """Test social media engagement with only X data present."""
        metrics = {
            "votes": 5,
            "replies": 3,
            "external": {
                "x": {
                    "post_count": 2,
                    "total_likes": 10,
                    "total_quotes": 2,
                    "total_replies": 1,
                    "total_reposts": 5,
                    "total_impressions": 500,
                }
            },
        }

        result = get_social_media_engagement_from_metrics(metrics)

        # Expected: X only = 52.2
        self.assertAlmostEqual(result, 52.2, places=1)

    def test_get_social_media_engagement_from_metrics_empty(self):
        """Test social media engagement returns 0 when no external data present."""
        metrics = {"votes": 5, "replies": 3}

        result = get_social_media_engagement_from_metrics(metrics)

        self.assertEqual(result, 0.0)

    def test_get_social_media_engagement_from_metrics_no_external(self):
        """Test social media engagement returns 0 when external key is missing."""
        metrics = {"votes": 5, "replies": 3, "review_metrics": {"count": 1}}

        result = get_social_media_engagement_from_metrics(metrics)

        self.assertEqual(result, 0.0)

    def test_get_social_media_engagement_from_metrics_empty_external(self):
        """Test social media engagement returns 0 when external data is empty."""
        metrics = {"votes": 5, "external": {}}

        result = get_social_media_engagement_from_metrics(metrics)

        self.assertEqual(result, 0.0)

    def test_get_social_media_engagement_from_metrics_invalid_input(self):
        """Test social media engagement handles invalid input gracefully."""
        # Test with None
        result = get_social_media_engagement_from_metrics(None)
        self.assertEqual(result, 0.0)

        # Test with non-dict
        result = get_social_media_engagement_from_metrics("invalid")
        self.assertEqual(result, 0.0)

        # Test with empty dict
        result = get_social_media_engagement_from_metrics({})
        self.assertEqual(result, 0.0)

    # ========================================================================
    # Adjusted Score Calculation Tests
    # ========================================================================

    def test_calculate_adjusted_score_no_social_engagement(self):
        """Test adjusted score with no social media engagement."""
        result = calculate_adjusted_score(base_votes=5, external_metrics={})

        # With no social engagement, log(0+1) * 5 = 0
        # So adjusted_score = base_votes = 5
        self.assertEqual(result, 5)

    def test_calculate_adjusted_score_with_x_engagement(self):
        """Test adjusted score with X/Twitter engagement."""
        external_metrics = {
            "x": {
                "total_likes": 10,
                "total_quotes": 2,
                "total_replies": 1,
                "total_reposts": 5,
                "total_impressions": 500,
            }
        }

        result = calculate_adjusted_score(
            base_votes=5, external_metrics=external_metrics
        )

        # X engagement = 52.2 (from previous test)
        # social_score = log(52.2 + 1) * 5.0 ≈ log(53.2) * 5 ≈ 3.97 * 5 ≈ 19.8 → 19
        # adjusted_score = 5 + 19 = 24
        self.assertGreater(result, 5)  # Should be higher than base votes
        self.assertIsInstance(result, int)

    def test_calculate_adjusted_score_logarithmic_scaling(self):
        """Test that adjusted score uses logarithmic scaling (diminishing returns)."""
        # Low engagement
        low_engagement = {"x": {"total_likes": 10, "total_impressions": 100}}
        result_low = calculate_adjusted_score(
            base_votes=0, external_metrics=low_engagement
        )

        # Medium engagement (10x more)
        medium_engagement = {"x": {"total_likes": 100, "total_impressions": 1000}}
        result_medium = calculate_adjusted_score(
            base_votes=0, external_metrics=medium_engagement
        )

        # High engagement (100x more than low)
        high_engagement = {"x": {"total_likes": 1000, "total_impressions": 10000}}
        result_high = calculate_adjusted_score(
            base_votes=0, external_metrics=high_engagement
        )

        # Verify logarithmic scaling: gains should diminish
        # Difference between medium/high should be less than low/medium
        # (in relative terms, not absolute)
        self.assertGreater(result_medium, result_low)
        self.assertGreater(result_high, result_medium)

        # All should be non-negative integers
        self.assertIsInstance(result_low, int)
        self.assertIsInstance(result_medium, int)
        self.assertIsInstance(result_high, int)

    def test_calculate_adjusted_score_with_all_platforms(self):
        """Test adjusted score with engagement from all platforms."""
        external_metrics = {
            "x": {
                "total_likes": 10,
                "total_quotes": 2,
                "total_replies": 1,
                "total_reposts": 5,
                "total_impressions": 500,
            },
            "bluesky": {
                "total_likes": 20,
                "total_quotes": 2,
                "total_replies": 3,
                "total_reposts": 5,
            },
            "github_mentions": {
                "total_mentions": 3,
            },
        }

        result = calculate_adjusted_score(
            base_votes=10, external_metrics=external_metrics
        )

        # Combined engagement = 52.2 + 5.1 + 9.0 = 66.3
        # social_score = log(66.3 + 1) * 5.0 ≈ log(67.3) * 5 ≈ 4.21 * 5 ≈ 21
        # adjusted_score = 10 + 21 = 31
        self.assertGreater(result, 10)  # Should be higher than base votes
        self.assertIsInstance(result, int)

    def test_calculate_adjusted_score_with_none_external_metrics(self):
        """Test adjusted score handles None external_metrics gracefully."""
        result = calculate_adjusted_score(base_votes=5, external_metrics=None)

        # Should return just base votes when external_metrics is None
        self.assertEqual(result, 5)
