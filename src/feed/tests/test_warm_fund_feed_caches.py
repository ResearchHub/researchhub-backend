"""Warm/replace and disable_cache coverage for Grant and Funding homepage caches."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.urls import reverse
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from feed.cache_segment import FEED_CACHE_TIMEOUT
from feed.funding_feed_cache import (
    FUNDING_FEED_WARM_COMPLETED_STATUS,
    FUNDING_FEED_WARM_ORDERINGS,
    should_cache_funding_feed,
)
from feed.grant_feed_cache import should_cache_grant_feed
from feed.tasks import warm_funding_feed_cache, warm_grant_feed_cache
from feed.views.funding_feed_view import FundingFeedViewSet
from feed.views.grant_feed_view import GrantFeedViewSet
from purchase.models import Grant
from purchase.related_models.constants.currency import USD
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import AWSMockTestCase


class FundingFeedCacheEligibilityTests(AWSMockTestCase):
    """Cache only warm/invalidate specs — not OPEN / include_ended / etc."""

    def _request(self, params=None):
        req = Request(APIRequestFactory().get("/api/funding_feed/", params or {}))
        req.user = AnonymousUser()
        return req

    def test_warm_specs_are_cacheable(self):
        # Arrange / Act / Assert
        self.assertTrue(
            should_cache_funding_feed(self._request({"page": "1", "page_size": "20"}))
        )
        for ordering in FUNDING_FEED_WARM_ORDERINGS:
            self.assertTrue(
                should_cache_funding_feed(
                    self._request(
                        {"page": "1", "page_size": "20", "ordering": ordering}
                    )
                ),
                ordering,
            )
        self.assertTrue(
            should_cache_funding_feed(
                self._request(
                    {
                        "page": "1",
                        "page_size": "20",
                        "fundraise_status": FUNDING_FEED_WARM_COMPLETED_STATUS,
                    }
                )
            )
        )

    def test_non_warm_variants_are_not_cacheable(self):
        # Arrange / Act / Assert
        cases = [
            {"page": "1", "page_size": "20", "fundraise_status": "OPEN"},
            {"page": "1", "page_size": "20", "include_ended": "false"},
            {"page": "1", "page_size": "20", "source": "researchhub"},
            {"page": "1", "page_size": "20", "hub_slug": "biology"},
            {"page": "1", "page_size": "20", "feed_view": "following"},
            {
                "page": "1",
                "page_size": "20",
                "ordering": "newest",
                "fundraise_status": "CLOSED",
            },
            {"page": "1", "page_size": "20", "ordering": "upvotes"},
        ]
        for params in cases:
            self.assertFalse(
                should_cache_funding_feed(self._request(params)),
                params,
            )


class GrantFundingWarmCacheTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.factory = APIRequestFactory()
        self.owner = create_random_authenticated_user("warm_grant_owner")
        self.grant_post = create_post(
            created_by=self.owner, document_type=GRANT, title="Warm Public Grant"
        )
        Grant.objects.create(
            created_by=self.owner,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency=USD,
            organization="Org",
            description="desc",
            status=Grant.OPEN,
        )
        self.private_post = create_post(
            created_by=self.owner,
            document_type=PREREGISTRATION,
            title="Warm Private Proposal",
        )
        self.private_post.unified_document.is_public = False
        self.private_post.unified_document.save()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _anon_request(self, path, params=None):
        req = Request(self.factory.get(path, params or {}))
        req.user = AnonymousUser()
        return req

    def test_warm_grant_feed_cache_sets_public_and_admin_keys(self):
        # Act
        warm_grant_feed_cache()

        # Assert
        view = GrantFeedViewSet()
        req = self._anon_request("/api/grant_feed/", {"page": "1", "page_size": "20"})
        base = view.get_cache_key(req, "grants")
        self.assertIsNotNone(cache.get(base + ":public"))
        self.assertIsNotNone(cache.get(base + ":admin"))
        self.assertIsNone(cache.get(base + f":viewer-{self.owner.id}"))

    def test_warm_funding_feed_cache_sets_public_and_admin_keys(self):
        # Act
        warm_funding_feed_cache()

        # Assert
        view = FundingFeedViewSet()
        req = self._anon_request("/api/funding_feed/", {"page": "1", "page_size": "20"})
        base = view.get_cache_key(req, "funding")
        self.assertIsNotNone(cache.get(base + ":public"))
        self.assertIsNotNone(cache.get(base + ":admin"))
        self.assertIsNone(cache.get(base + f":viewer-{self.owner.id}"))

    def test_public_warm_payload_excludes_private_posts(self):
        # Arrange / Act
        warm_funding_feed_cache()
        view = FundingFeedViewSet()
        req = self._anon_request("/api/funding_feed/", {"page": "1", "page_size": "20"})
        payload = cache.get(view.get_cache_key(req, "funding") + ":public")

        # Assert
        self.assertIsNotNone(payload)
        ids = {item["content_object"]["id"] for item in payload["results"]}
        self.assertNotIn(self.private_post.id, ids)

    def test_admin_warm_payload_includes_private_posts(self):
        # Arrange / Act
        warm_funding_feed_cache()
        view = FundingFeedViewSet()
        req = self._anon_request("/api/funding_feed/", {"page": "1", "page_size": "20"})
        payload = cache.get(view.get_cache_key(req, "funding") + ":admin")

        # Assert
        self.assertIsNotNone(payload)
        ids = {item["content_object"]["id"] for item in payload["results"]}
        self.assertIn(self.private_post.id, ids)

    def test_shared_ttl_is_ten_minutes(self):
        # Assert
        self.assertEqual(FEED_CACHE_TIMEOUT, 60 * 10)


class GrantFundingDisableCacheTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.moderator = create_random_authenticated_user(
            "disable_cache_mod", moderator=True
        )
        self.user = create_random_authenticated_user("disable_cache_user")
        self.client = APIClient()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    @patch("feed.views.grant_feed_view.cache")
    def test_moderator_disable_cache_skips_grant_cache(self, mock_cache):
        # Arrange
        mock_cache.get.return_value = None
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(
            "/api/grant_feed/", {"page": 1, "page_size": 20, "disable_cache": "true"}
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()

    @patch("feed.views.funding_feed_view.cache")
    def test_moderator_disable_cache_skips_funding_cache(self, mock_cache):
        # Arrange
        mock_cache.get.return_value = None
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(
            reverse("funding_feed-list"),
            {"page": 1, "page_size": 20, "disable_cache": "true"},
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        mock_cache.get.assert_not_called()
        mock_cache.set.assert_not_called()

    def test_non_mod_disable_cache_ignored_for_eligibility(self):
        # Arrange
        factory = APIRequestFactory()
        req = Request(
            factory.get(
                "/api/funding_feed/",
                {"page": "1", "page_size": "20", "disable_cache": "true"},
            )
        )
        req.user = self.user
        grant_req = Request(
            factory.get(
                "/api/grant_feed/",
                {"page": "1", "page_size": "20", "disable_cache": "true"},
            )
        )
        grant_req.user = self.user

        # Act / Assert
        self.assertTrue(should_cache_funding_feed(req))
        self.assertTrue(should_cache_grant_feed(grant_req))
