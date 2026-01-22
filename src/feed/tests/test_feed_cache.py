"""
Tests for feed cache invalidation.
"""

from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from analytics.constants.event_types import UPVOTE
from analytics.models import UserInteractions
from feed.models import FeedEntry
from feed.views.feed_view_mixin import FeedViewMixin
from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow
from utils.test_helpers import AWSMockTestCase


class CacheInvalidationTests(AWSMockTestCase):
    """Test cache invalidation for feed views."""

    def setUp(self):
        """Set up test cache keys."""
        super().setUp()
        self.user_id = 123
        cache.clear()

    def tearDown(self):
        """Clean up cache after each test."""
        cache.clear()

    def test_invalidate_feed_cache_for_user_clears_main_feed_caches(self):
        """Test that main feed caches are cleared for a user."""
        cache_keys = [
            f"feed:following:all:all:{self.user_id}:1-20",
            f"feed:following:all:all:{self.user_id}:2-20",
            f"feed:following:all:all:{self.user_id}:3-20",
            f"feed:following:all:all:{self.user_id}:4-20",
        ]

        for key in cache_keys:
            cache.set(key, {"test": "data"})

        for key in cache_keys:
            self.assertIsNotNone(cache.get(key))

        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

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

        for key in cache_keys:
            cache.set(key, {"test": "data"})

        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

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

        for key in cache_keys:
            cache.set(key, {"test": "data"})

        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        for key in cache_keys:
            self.assertIsNone(cache.get(key))

    def test_invalidate_feed_cache_does_not_affect_other_users(self):
        """Test that cache invalidation only affects the specified user."""
        other_user_id = 456

        user_cache_key = f"feed:following:all:all:{self.user_id}:1-20"
        other_user_cache_key = f"feed:following:all:all:{other_user_id}:1-20"

        cache.set(user_cache_key, {"user": "data"})
        cache.set(other_user_cache_key, {"other": "data"})

        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        self.assertIsNone(cache.get(user_cache_key))
        self.assertIsNotNone(cache.get(other_user_cache_key))
        self.assertEqual(cache.get(other_user_cache_key), {"other": "data"})

    def test_invalidate_feed_cache_does_not_affect_popular_feed(self):
        """Test that popular feed caches (user=none) are not affected."""
        popular_cache_key = "feed:popular:all:all:none:1-20"
        user_cache_key = f"feed:following:all:all:{self.user_id}:1-20"

        cache.set(popular_cache_key, {"popular": "data"})
        cache.set(user_cache_key, {"user": "data"})

        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        self.assertIsNotNone(cache.get(popular_cache_key))
        self.assertEqual(cache.get(popular_cache_key), {"popular": "data"})
        self.assertIsNone(cache.get(user_cache_key))

    def test_invalidate_feed_cache_for_user_handles_no_existing_cache(self):
        """Test that invalidation works even when no caches exist."""
        try:
            FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)
        except Exception as e:
            self.fail(f"invalidate_feed_cache_for_user raised {e} unexpectedly")

    @patch("feed.views.feed_view_mixin.cache")
    def test_invalidate_feed_cache_calls_delete_for_expected_keys(self, mock_cache):
        """Test that cache.delete is called for all expected cache keys."""
        FeedViewMixin.invalidate_feed_cache_for_user(self.user_id)

        self.assertGreater(mock_cache.delete.call_count, 0)

        delete_call_args = [call[0][0] for call in mock_cache.delete.call_args_list]

        expected_keys = [
            f"feed:following:all:all:{self.user_id}:1-20",
            f"feed:following:all:all:{self.user_id}:2-20",
            f"feed:following:all:all:{self.user_id}:3-20",
            f"feed:following:all:all:{self.user_id}:4-20",
        ]

        for expected_key in expected_keys:
            self.assertIn(expected_key, delete_call_args)


class FeedCachingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        """Set up test data once for all tests in this class."""
        cls.user = create_random_default_user("cache_test_user")
        cls.hub, _ = Hub.objects.get_or_create(
            slug="biorxiv", defaults={"name": "bioRxiv"}
        )

        cls.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="POST"
        )
        cls.unified_document.hubs.add(cls.hub)

        create_follow(cls.user, cls.hub)

        cls.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        cls.paper_content_type = ContentType.objects.get_for_model(Paper)

        for i in range(25):
            if i % 2 == 0:
                unified_doc = ResearchhubUnifiedDocument.objects.create(
                    document_type="PAPER"
                )
                unified_doc.hubs.add(cls.hub)

                paper = Paper.objects.create(
                    title=f"Test Paper {i}",
                    paper_publish_date=timezone.now(),
                    unified_document=unified_doc,
                )

                feed_entry = FeedEntry.objects.create(
                    action="PUBLISH",
                    action_date=timezone.now(),
                    object_id=paper.id,
                    content_type=cls.paper_content_type,
                    unified_document=unified_doc,
                    content={},
                    metrics={},
                    pdf_copyright_allows_display=True,
                )
                feed_entry.hubs.add(cls.hub)
            else:
                unified_doc = ResearchhubUnifiedDocument.objects.create(
                    document_type="POST"
                )
                unified_doc.hubs.add(cls.hub)

                post = ResearchhubPost.objects.create(
                    title=f"Test Post {i}",
                    document_type="POST",
                    created_by=cls.user,
                    unified_document=unified_doc,
                )

                feed_entry = FeedEntry.objects.create(
                    action="PUBLISH",
                    action_date=timezone.now(),
                    object_id=post.id,
                    content_type=cls.post_content_type,
                    unified_document=unified_doc,
                    content={},
                    metrics={},
                )
                feed_entry.hubs.add(cls.hub)

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _create_interactions_for_user(self, user, count=5):
        """Create interactions to pass cold-start threshold."""
        for i in range(count):
            # Create a paper for each interaction
            unified_doc = ResearchhubUnifiedDocument.objects.create(
                document_type="PAPER"
            )
            unified_doc.hubs.add(self.hub)
            paper = Paper.objects.create(
                title=f"Interaction Paper {user.id}_{i}",
                paper_publish_date=timezone.now(),
                unified_document=unified_doc,
            )
            UserInteractions.objects.create(
                user=user,
                event=UPVOTE,
                unified_document=unified_doc,
                content_type=self.paper_content_type,
                object_id=paper.id,
                event_timestamp=timezone.now(),
            )

    def test_pages_1_through_4_are_cached(self):
        url = reverse("feed-list")

        for page in range(1, 5):
            response1 = self.client.get(url, {"page": page, "ordering": "hot_score_v2"})
            self.assertEqual(response1.status_code, 200)
            self.assertEqual(response1["RH-Cache"], "miss")

            response2 = self.client.get(url, {"page": page, "ordering": "hot_score_v2"})
            self.assertEqual(response2.status_code, 200)
            self.assertEqual(response2["RH-Cache"], "hit")

    def test_page_5_and_beyond_not_cached(self):
        url = reverse("feed-list")

        response1 = self.client.get(url, {"page": 5})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"page": 5})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2["RH-Cache"], "miss")

    def test_health_check_token_bypasses_cache(self):
        url = reverse("feed-list")

        response1 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response2["RH-Cache"], "hit")

        response3 = self.client.get(
            url,
            {
                "ordering": "hot_score_v2",
                "disable_cache": settings.HEALTH_CHECK_TOKEN,
            },
        )
        self.assertEqual(response3["RH-Cache"], "miss")

    def test_cache_hit_includes_header_for_authenticated_user(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        response2 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response2["RH-Cache"], "hit (auth)")

    def test_cache_hit_includes_header_for_anonymous_user(self):
        url = reverse("feed-list")

        response1 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response2["RH-Cache"], "hit")

    def test_cache_miss_includes_header(self):
        url = reverse("feed-list")

        response = self.client.get(url)
        self.assertEqual(response["RH-Cache"], "miss")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_cache_key_differs_by_feed_view(self, mock_get_recommendations):
        # Create interactions to pass cold-start threshold
        self._create_interactions_for_user(self.user, 5)

        feed_entries = FeedEntry.objects.filter(content_type=self.paper_content_type)[
            :10
        ]
        mock_get_recommendations.return_value = {
            "item_ids": [e.unified_document_id for e in feed_entries],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score_v2"}
        )
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        response2 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(response2["RH-Cache"], "miss (auth)")

        response3 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response3["RH-Cache"], "partial-cache-miss (auth)")

        response4 = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score_v2"}
        )
        self.assertEqual(response4["RH-Cache"], "hit (auth)")

    def test_cache_key_differs_by_ordering(self):
        url = reverse("feed-list")

        response1 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"ordering": "hot_score"})
        self.assertEqual(response2["RH-Cache"], "miss")

        response3 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response3["RH-Cache"], "hit")

    def test_cache_key_differs_by_hub_slug(self):
        url = reverse("feed-list")
        hub2 = Hub.objects.create(name="Another Hub", slug="another-hub")

        response1 = self.client.get(
            url, {"hub_slug": self.hub.slug, "ordering": "hot_score_v2"}
        )
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(
            url, {"hub_slug": hub2.slug, "ordering": "hot_score_v2"}
        )
        self.assertEqual(response2["RH-Cache"], "miss")

        response3 = self.client.get(
            url, {"hub_slug": self.hub.slug, "ordering": "hot_score_v2"}
        )
        self.assertEqual(response3["RH-Cache"], "hit")

    def test_cache_key_includes_researchhub_feed_type(self):
        """Test that feed requests are cached (cache key format is internal)."""
        url = reverse("feed-list")

        # First request should be a cache miss
        response1 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1["RH-Cache"], "miss")

        # Second request should be a cache hit (proving caching works)
        response2 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2["RH-Cache"], "hit")

    @patch("feed.views.feed_view.cache")
    def test_following_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "following"})

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_feed_respects_use_cache_config(
        self, mock_get_recommendations
    ):
        """
        Test that personalized feed doesn't use full-page caching.
        Note: cache IS used for interaction counting, but not for response caching.
        """
        # Create interactions to pass cold-start threshold
        self._create_interactions_for_user(self.user, 5)

        feed_entries = FeedEntry.objects.filter(content_type=self.paper_content_type)[
            :5
        ]
        mock_get_recommendations.return_value = {
            "item_ids": [e.unified_document_id for e in feed_entries],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        # First request - should be cache miss (partial)
        response1 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response1["RH-Cache"], "partial-cache-miss (auth)")

        # Second request - should be cache hit (partial, IDs cached)
        response2 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response2["RH-Cache"], "partial-cache-hit (auth)")

    @patch("feed.views.feed_view.cache")
    def test_popular_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("feed-list")

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "popular", "ordering": "hot_score_v2"})

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

    def test_cache_key_differs_by_user_id_parameter(self):
        """
        Test that when user_id query parameter is used,
        cache keys are different from authenticated user's cache.
        This prevents cache collision when admins request feeds for different users.
        """
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        other_user = create_random_default_user("other_cache_user")
        response2 = self.client.get(
            url, {"feed_view": "following", "user_id": str(other_user.id)}
        )
        self.assertEqual(response2["RH-Cache"], "miss (auth)")

        response3 = self.client.get(
            url, {"feed_view": "following", "user_id": str(other_user.id)}
        )
        self.assertEqual(response3["RH-Cache"], "hit (auth)")

        response4 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(response4["RH-Cache"], "hit (auth)")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_feed_service_layer_caching(self, mock_get_recommendations):
        """
        Test that personalized feed uses service layer caching.
        IDs are cached and reused across multiple page requests.
        """
        # Create interactions to pass cold-start threshold
        self._create_interactions_for_user(self.user, 5)

        feed_entries = list(
            FeedEntry.objects.filter(content_type=self.paper_content_type)
        )
        mock_get_recommendations.return_value = {
            "item_ids": [entry.unified_document_id for entry in feed_entries],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(mock_get_recommendations.call_count, 1)

        response2 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(mock_get_recommendations.call_count, 1)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_feed_cache_header(self, mock_get_recommendations):
        # Create interactions to pass cold-start threshold
        self._create_interactions_for_user(self.user, 5)

        feed_entries = FeedEntry.objects.filter(content_type=self.paper_content_type)[
            :5
        ]
        mock_get_recommendations.return_value = {
            "item_ids": [e.unified_document_id for e in feed_entries],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1["RH-Cache"], "partial-cache-miss (auth)")

        response2 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2["RH-Cache"], "partial-cache-hit (auth)")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_votes_are_added_to_personalized_feed_response(
        self, mock_get_recommendations
    ):
        from discussion.models import Vote

        # Create interactions to pass cold-start threshold
        self._create_interactions_for_user(self.user, 5)

        feed_entry = FeedEntry.objects.filter(
            content_type=self.paper_content_type
        ).first()
        mock_get_recommendations.return_value = {
            "item_ids": [feed_entry.unified_document_id],
            "recommendation_id": "test-rec-id",
        }

        Vote.objects.create(
            content_type=feed_entry.content_type,
            object_id=feed_entry.object_id,
            created_by=self.user,
            vote_type=1,
        )

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response.status_code, 200)

        self.assertGreater(len(response.data["results"]), 0)
        first_result = response.data["results"][0]
        self.assertIn("user_vote", first_result)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_feed_pagination_across_multiple_pages(
        self, mock_get_recommendations
    ):
        # Create interactions to pass cold-start threshold
        self._create_interactions_for_user(self.user, 5)

        feed_entries = list(
            FeedEntry.objects.filter(content_type=self.paper_content_type)
        )
        unified_doc_ids = [entry.unified_document_id for entry in feed_entries]

        mock_get_recommendations.return_value = {
            "item_ids": unified_doc_ids,
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "personalized", "page": "1"})
        self.assertEqual(response1.status_code, 200)
        page1_results = response1.data["results"]
        self.assertGreater(len(page1_results), 0)

        # Recommendations are cached, so only one call should be made
        self.assertEqual(mock_get_recommendations.call_count, 1)
