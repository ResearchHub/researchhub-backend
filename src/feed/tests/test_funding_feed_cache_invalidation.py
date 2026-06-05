from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from feed.views.common import FeedPagination
from feed.views.funding_cache_mixin import FundingCacheMixin
from feed.views.funding_feed_view import FundingFeedViewSet


class FundingFeedCacheInvalidationTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_invalidate_uses_same_key_as_viewset_get_cache_key(self):
        factory = APIRequestFactory()
        drf_request = Request(factory.get("/api/funding_feed/"))
        drf_request.user = MagicMock()
        drf_request.user.is_authenticated = False
        drf_request.user.id = None

        view = FundingFeedViewSet()
        view.pagination_class = FeedPagination
        expected = view.get_cache_key(drf_request, "funding")

        factory2 = APIRequestFactory()
        same_params = {
            "page": "1",
            "page_size": str(FeedPagination.page_size),
            "feed_view": "popular",
        }
        drf2 = Request(factory2.get("/api/funding_feed/", same_params))
        drf2.user = MagicMock()
        drf2.user.is_authenticated = False
        drf2.user.id = None
        explicit = view.get_cache_key(drf2, "funding")
        self.assertEqual(explicit, expected)

    def test_invalidate_clears_matching_cache_entry(self):
        view = FundingFeedViewSet()
        view.pagination_class = FeedPagination
        factory = APIRequestFactory()
        params = {
            "page": "1",
            "page_size": str(FeedPagination.page_size),
            "feed_view": "popular",
        }
        req = Request(factory.get("/api/funding_feed/", params))
        req.user = MagicMock()
        req.user.is_authenticated = False
        req.user.id = None
        k = view.get_cache_key(req, "funding")
        cache.set(k, {"cached": True}, timeout=3600)
        self.assertIsNotNone(cache.get(k))
        FundingCacheMixin.invalidate_funding_feed_cache()
        self.assertIsNone(cache.get(k))
