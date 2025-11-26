from unittest.mock import Mock

from django.test import TestCase

from feed.views.feed_view_mixin import FeedViewMixin


class FeedViewMixinTests(TestCase):
    def test_get_cache_key(self):
        """Test cache key generation method with various inputs"""
        # Arrange
        view = FeedViewMixin()

        test_cases = [
            # (query_params, is_authenticated, user_id, expected_key)
            (
                {},
                False,
                None,
                "feed:popular:all:all:none:1-20",
            ),
            (
                {"source": "researchhub"},
                False,
                None,
                "feed:popular:all:researchhub:none:1-20",
            ),
            (
                {"feed_view": "following"},
                True,
                123,
                "feed:following:all:all:123:1-20",
            ),
            (
                {"hub_slug": "science"},
                False,
                None,
                "feed:popular:science:all:none:1-20",
            ),
            (
                {"feed_view": "popular"},
                True,
                123,
                "feed:popular:all:all:none:1-20",
            ),
            (
                {"feed_view": "latest"},
                False,
                None,
                "feed:latest:all:all:none:1-20",
            ),
            (
                {"page": "3", "page_size": "50"},
                False,
                None,
                "feed:popular:all:all:none:3-50",
            ),
            (
                {
                    "feed_view": "following",
                    "hub_slug": "computer-science",
                    "page": "2",
                    "page_size": "30",
                },
                True,
                456,
                "feed:following:computer-science:all:456:2-30",
            ),
        ]

        for query_params, is_authenticated, user_id, expected_key in test_cases:
            mock_request = Mock()
            mock_request.query_params = query_params
            mock_request.user = Mock()
            mock_request.user.is_authenticated = is_authenticated
            mock_request.user.id = user_id

            # Act
            cache_key = view.get_cache_key(
                mock_request,
            )

            # Assert
            self.assertEqual(
                cache_key,
                expected_key,
                f"Failed with params: {query_params}, auth: {is_authenticated}, "
                f"user_id: {user_id}",
            )

    def test_cache_key_defaults_to_popular(self):
        """
        Test that cache key defaults to 'popular' when feed_view is not provided.

        This prevents cache collision between popular and latest feeds when clients
        omit the feed_view parameter (since popular is the default in the view).
        """
        view = FeedViewMixin()

        mock_request = Mock()
        mock_request.query_params = {}  # No feed_view provided
        mock_request.user = Mock()
        mock_request.user.is_authenticated = False
        mock_request.user.id = None

        cache_key = view.get_cache_key(mock_request)

        # Should use 'popular' as default, NOT 'latest'
        self.assertIn("feed:popular:", cache_key)
