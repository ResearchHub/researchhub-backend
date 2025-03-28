from unittest.mock import Mock

from django.test import TestCase

from feed.views.common import get_cache_key
from feed.views.feed_view import FeedViewSet


class FeedCommonTests(TestCase):
    def test_get_cache_key(self):
        """Test cache key generation method with various inputs"""
        # Arrange
        viewset = FeedViewSet()
        viewset.pagination_class = type(
            "TestPagination",
            (),
            {"page_size": 20, "page_size_query_param": "page_size"},
        )

        test_cases = [
            # (query_params, is_authenticated, user_id, expected_key)
            ({}, False, None, "feed:latest:all:none:1-20"),
            ({"feed_view": "following"}, True, 123, "feed:following:all:123:1-20"),
            (
                {"hub_slug": "science"},
                False,
                None,
                "feed:latest:science:none:1-20",
            ),
            ({"feed_view": "popular"}, True, 123, "feed:popular:all:none:1-20"),
            (
                {"page": "3", "page_size": "50"},
                False,
                None,
                "feed:latest:all:none:3-50",
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
                "feed:following:computer-science:456:2-30",
            ),
        ]

        for query_params, is_authenticated, user_id, expected_key in test_cases:
            mock_request = Mock()
            mock_request.query_params = query_params
            mock_request.user = Mock()
            mock_request.user.is_authenticated = is_authenticated
            mock_request.user.id = user_id

            # Act
            cache_key = get_cache_key(
                mock_request,
            )

            # Assert
            self.assertEqual(
                cache_key,
                expected_key,
                f"Failed with params: {query_params}, auth: {is_authenticated}, "
                f"user_id: {user_id}",
            )
