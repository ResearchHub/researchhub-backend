"""
Tests for feed cache invalidation.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from feed.views.feed_view_mixin import FeedViewMixin


class CacheInvalidationTests(TestCase):
    """Test cache invalidation for feed views."""

    def setUp(self):
        """Set up test cache keys."""
        self.user_id = 123
        cache.clear()

    def tearDown(self):
        """Clean up cache after each test."""
        cache.clear()

    def test_invalidate_feed_cache_for_user_clears_main_feed_caches(self):
        """Test that main feed caches are cleared for a user."""
        # Set up some cache entries
        cache_keys = [
            f"feed:following:all:all:{self.user_id}:1-20",
            f"feed:following:all:all:{self.user_id}:2-20",
            f"feed:following:all:all:{self.user_id}:3-20",
            f"feed:following:all:all:{self.user_id}:4-20",
        ]

        # Set cache values
        for key in cache_keys:
            cache.set(key, {"test": "data"})

        # Verify caches are set
        for key in cache_keys:
            self.assertIsNotNone(cache.get(key))

        # Invalidate caches
        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        # Verify caches are cleared
        for key in cache_keys:
            self.assertIsNone(cache.get(key))

    def test_invalidate_feed_cache_for_user_clears_researchhub_source_caches(self):
        """Test that researchhub source filtered caches are cleared."""
        cache_keys = [
            f"feed:following:all:researchhub:{self.user_id}:1-20",
            f"feed:following:all:researchhub:{self.user_id}:2-20",
            f"feed:following:all:researchhub:{self.user_id}:3-20",
            f"feed:following:all:researchhub:{self.user_id}:4-20",
        ]

        # Set cache values
        for key in cache_keys:
            cache.set(key, {"test": "data"})

        # Invalidate caches
        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        # Verify caches are cleared
        for key in cache_keys:
            self.assertIsNone(cache.get(key))

    def test_invalidate_feed_cache_for_user_clears_hot_score_sorted_caches(self):
        """Test that hot_score sorted caches are cleared."""
        cache_keys = [
            f"feed:following:all:all:{self.user_id}:1-20-hot_score",
            f"feed:following:all:all:{self.user_id}:2-20-hot_score",
            f"feed:following:all:all:{self.user_id}:3-20-hot_score",
            f"feed:following:all:all:{self.user_id}:4-20-hot_score",
        ]

        # Set cache values
        for key in cache_keys:
            cache.set(key, {"test": "data"})

        # Invalidate caches
        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        # Verify caches are cleared
        for key in cache_keys:
            self.assertIsNone(cache.get(key))

    def test_invalidate_feed_cache_does_not_affect_other_users(self):
        """Test that cache invalidation only affects the specified user."""
        other_user_id = 456

        # Set cache for both users
        user_cache_key = f"feed:following:all:all:{self.user_id}:1-20"
        other_user_cache_key = f"feed:following:all:all:{other_user_id}:1-20"

        cache.set(user_cache_key, {"user": "data"})
        cache.set(other_user_cache_key, {"other": "data"})

        # Invalidate only for self.user_id
        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        # Verify only target user's cache is cleared
        self.assertIsNone(cache.get(user_cache_key))
        self.assertIsNotNone(cache.get(other_user_cache_key))
        self.assertEqual(cache.get(other_user_cache_key), {"other": "data"})

    def test_invalidate_feed_cache_does_not_affect_popular_feed(self):
        """Test that popular feed caches (user=none) are not affected."""
        # Popular feed uses 'none' instead of user_id
        popular_cache_key = "feed:popular:all:all:none:1-20"
        user_cache_key = f"feed:following:all:all:{self.user_id}:1-20"

        cache.set(popular_cache_key, {"popular": "data"})
        cache.set(user_cache_key, {"user": "data"})

        # Invalidate user cache
        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        # Verify popular cache is not affected
        self.assertIsNotNone(cache.get(popular_cache_key))
        self.assertEqual(cache.get(popular_cache_key), {"popular": "data"})
        self.assertIsNone(cache.get(user_cache_key))

    def test_invalidate_feed_cache_for_user_handles_no_existing_cache(self):
        """Test that invalidation works even when no caches exist."""
        # This should not raise any errors
        try:
            FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)
        except Exception as e:
            self.fail(f"invalidate_feed_cache_for_user raised {e} unexpectedly")

    @patch("feed.views.feed_view_mixin.cache")
    def test_invalidate_feed_cache_calls_delete_for_expected_keys(self, mock_cache):
        """Test that cache.delete is called for all expected cache keys."""
        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        # Verify that cache.delete was called multiple times
        self.assertGreater(mock_cache.delete.call_count, 0)

        # Check that some expected keys were in the delete calls
        delete_call_args = [call[0][0] for call in mock_cache.delete.call_args_list]

        # Verify some specific expected keys (only main feed, not funding)
        expected_keys = [
            f"feed:following:all:all:{self.user_id}:1-20",
            f"feed:following:all:all:{self.user_id}:2-20",
            f"feed:following:all:all:{self.user_id}:3-20",
            f"feed:following:all:all:{self.user_id}:4-20",
        ]

        for expected_key in expected_keys:
            self.assertIn(expected_key, delete_call_args)
