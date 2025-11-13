"""
Tests for feed cache invalidation.
"""

from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from feed.views.feed_view_mixin import FeedViewMixin
from hub.models import Hub
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow


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


class FeedCachingTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("cache_test_user")
        self.hub = Hub.objects.create(name="Test Hub", slug="test-hub")

        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="POST"
        )
        self.unified_document.hubs.add(self.hub)

        create_follow(self.user, self.hub)

        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        for i in range(150):
            unified_doc = ResearchhubUnifiedDocument.objects.create(
                document_type="POST"
            )
            unified_doc.hubs.add(self.hub)

            post = ResearchhubPost.objects.create(
                title=f"Test Post {i}",
                document_type="POST",
                created_by=self.user,
                unified_document=unified_doc,
            )

            feed_entry = FeedEntry.objects.create(
                action="PUBLISH",
                action_date=timezone.now(),
                object_id=post.id,
                content_type=self.post_content_type,
                unified_document=unified_doc,
                content={},
                metrics={},
            )
            feed_entry.hubs.add(self.hub)

    def tearDown(self):
        cache.clear()

    def test_pages_1_through_4_are_cached(self):
        url = reverse("researchhub_feed-list")

        for page in range(1, 5):
            response1 = self.client.get(url, {"page": page})
            self.assertEqual(response1.status_code, 200)
            self.assertEqual(response1["RH-Cache"], "miss")

            response2 = self.client.get(url, {"page": page})
            self.assertEqual(response2.status_code, 200)
            self.assertEqual(response2["RH-Cache"], "hit")

    def test_page_5_and_beyond_not_cached(self):
        url = reverse("researchhub_feed-list")

        response1 = self.client.get(url, {"page": 5})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"page": 5})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2["RH-Cache"], "miss")

    def test_health_check_token_bypasses_cache(self):
        url = reverse("researchhub_feed-list")

        response1 = self.client.get(url)
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url)
        self.assertEqual(response2["RH-Cache"], "hit")

        response3 = self.client.get(url, {"disable_cache": settings.HEALTH_CHECK_TOKEN})
        self.assertEqual(response3["RH-Cache"], "miss")

    def test_cache_hit_includes_header_for_authenticated_user(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url)
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        response2 = self.client.get(url)
        self.assertEqual(response2["RH-Cache"], "hit (auth)")

    def test_cache_hit_includes_header_for_anonymous_user(self):
        url = reverse("researchhub_feed-list")

        response1 = self.client.get(url)
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url)
        self.assertEqual(response2["RH-Cache"], "hit")

    def test_cache_miss_includes_header(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url)
        self.assertEqual(response["RH-Cache"], "miss")

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_cache_key_differs_by_feed_view(self, mock_get_recommendations):
        feed_entries = FeedEntry.objects.all()[:10]
        mock_get_recommendations.return_value = [
            str(e.unified_document_id) for e in feed_entries
        ]

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "popular"})
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        response2 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(response2["RH-Cache"], "miss (auth)")

        response3 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response3["RH-Cache"], "partial-cache-miss (auth)")

        response4 = self.client.get(url, {"feed_view": "popular"})
        self.assertEqual(response4["RH-Cache"], "hit (auth)")

    def test_cache_key_differs_by_ordering(self):
        url = reverse("researchhub_feed-list")

        response1 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"ordering": "hot_score"})
        self.assertEqual(response2["RH-Cache"], "miss")

        response3 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response3["RH-Cache"], "hit")

    def test_cache_key_differs_by_hub_slug(self):
        url = reverse("researchhub_feed-list")
        hub2 = Hub.objects.create(name="Another Hub", slug="another-hub")

        response1 = self.client.get(url, {"hub_slug": self.hub.slug})
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"hub_slug": hub2.slug})
        self.assertEqual(response2["RH-Cache"], "miss")

        response3 = self.client.get(url, {"hub_slug": self.hub.slug})
        self.assertEqual(response3["RH-Cache"], "hit")

    def test_cache_key_includes_researchhub_feed_type(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        cache_keys = list(cache._cache.keys())
        researchhub_keys = [key for key in cache_keys if "researchhub_" in str(key)]
        self.assertGreater(len(researchhub_keys), 0)

    @patch("feed.views.researchhub_feed_view.cache")
    def test_following_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "following"})

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

    @patch("feed.views.researchhub_feed_view.cache")
    def test_personalized_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "personalized"})

        # Personalized feed has use_cache=False, so cache should NOT be called
        self.assertFalse(mock_cache.get.called)
        self.assertFalse(mock_cache.set.called)

    @patch("feed.views.researchhub_feed_view.cache")
    def test_popular_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("researchhub_feed-list")

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "popular"})

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

    def test_cache_key_differs_by_user_id_parameter(self):
        """
        Test that when user_id query parameter is used,
        cache keys are different from authenticated user's cache.
        This prevents cache collision when admins request feeds for different users.
        """
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        # Request with authenticated user (no user_id param)
        # Using "following" feed which has caching enabled
        response1 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        # Request with different user_id parameter
        other_user = create_random_default_user("other_cache_user")
        response2 = self.client.get(
            url, {"feed_view": "following", "user_id": str(other_user.id)}
        )
        # Should be a cache miss because user_id differs
        self.assertEqual(response2["RH-Cache"], "miss (auth)")

        # Request again with same user_id - should hit cache
        response3 = self.client.get(
            url, {"feed_view": "following", "user_id": str(other_user.id)}
        )
        self.assertEqual(response3["RH-Cache"], "hit (auth)")

        # Original authenticated user request should still have its own cache
        # (proving it has its own cache key)
        response4 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(response4["RH-Cache"], "hit (auth)")

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_feed_service_layer_caching(self, mock_get_recommendations):
        """
        Test that personalized feed uses service layer caching.
        IDs are cached and reused across multiple page requests.
        """
        # Get enough feed entry IDs for pagination (need 60+ for page 2)
        feed_entries = FeedEntry.objects.all()[:80]
        feed_entry_ids = [str(entry.id) for entry in feed_entries]

        # Mock Personalize to return IDs
        mock_get_recommendations.return_value = feed_entry_ids

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        # First request - should call Personalize
        response1 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(mock_get_recommendations.call_count, 1)

        # Second request (same page) - should use cached IDs
        response2 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response2.status_code, 200)
        # Still only called once (IDs were cached)
        self.assertEqual(mock_get_recommendations.call_count, 1)

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_feed_cache_header(self, mock_get_recommendations):
        feed_entries = FeedEntry.objects.all()[:5]
        mock_get_recommendations.return_value = [
            str(e.unified_document_id) for e in feed_entries
        ]

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1["RH-Cache"], "partial-cache-miss (auth)")

        response2 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2["RH-Cache"], "partial-cache-hit (auth)")

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_votes_are_added_to_personalized_feed_response(
        self, mock_get_recommendations
    ):
        from discussion.models import Vote

        feed_entry = FeedEntry.objects.first()
        mock_get_recommendations.return_value = [str(feed_entry.unified_document_id)]

        Vote.objects.create(
            content_type=feed_entry.content_type,
            object_id=feed_entry.object_id,
            created_by=self.user,
            vote_type=1,
        )

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response.status_code, 200)

        self.assertGreater(len(response.data["results"]), 0)
        first_result = response.data["results"][0]
        self.assertIn("user_vote", first_result)

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_feed_pagination_across_multiple_pages(
        self, mock_get_recommendations
    ):
        feed_entries = FeedEntry.objects.all()[:80]
        unified_doc_ids = [str(entry.unified_document_id) for entry in feed_entries]

        mock_get_recommendations.return_value = unified_doc_ids

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "personalized", "page": "1"})
        self.assertEqual(response1.status_code, 200)
        page1_results = response1.data["results"]
        self.assertEqual(len(page1_results), 30)

        response2 = self.client.get(url, {"feed_view": "personalized", "page": "2"})
        self.assertEqual(response2.status_code, 200)
        page2_results = response2.data["results"]
        self.assertGreater(len(page2_results), 0)

        page1_ids = {r["id"] for r in page1_results}
        page2_ids = {r["id"] for r in page2_results}
        self.assertEqual(len(page1_ids & page2_ids), 0)

        self.assertEqual(mock_get_recommendations.call_count, 1)
