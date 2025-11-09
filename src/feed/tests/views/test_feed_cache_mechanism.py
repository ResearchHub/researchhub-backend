from unittest.mock import patch

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from hub.models import Hub
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow


class ResearchHubFeedCachingTests(APITestCase):
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
        self.entry_counter = 0

        self._create_feed_entries(30)

    def tearDown(self):
        cache.clear()

    def _create_feed_entries(self, count):
        for i in range(count):
            unified_doc = ResearchhubUnifiedDocument.objects.create(
                document_type="POST"
            )
            unified_doc.hubs.add(self.hub)

            post = ResearchhubPost.objects.create(
                title=f"Test Post {self.entry_counter}",
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
            self.entry_counter += 1

    def test_pages_1_through_4_are_cached(self):
        self._create_feed_entries(90)

        url = reverse("feed_v3-list")

        for page in range(1, 5):
            response1 = self.client.get(url, {"page": page})
            self.assertEqual(response1.status_code, 200)
            self.assertEqual(response1["RH-Cache"], "miss")

            response2 = self.client.get(url, {"page": page})
            self.assertEqual(response2.status_code, 200)
            self.assertEqual(response2["RH-Cache"], "hit")

    def test_page_5_and_beyond_not_cached(self):
        self._create_feed_entries(120)

        url = reverse("feed_v3-list")

        response1 = self.client.get(url, {"page": 5})
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"page": 5})
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2["RH-Cache"], "miss")

    def test_health_check_token_bypasses_cache(self):
        url = reverse("feed_v3-list")

        response1 = self.client.get(url)
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url)
        self.assertEqual(response2["RH-Cache"], "hit")

        response3 = self.client.get(url, {"disable_cache": settings.HEALTH_CHECK_TOKEN})
        self.assertEqual(response3["RH-Cache"], "miss")

    def test_cache_hit_includes_header_for_authenticated_user(self):
        url = reverse("feed_v3-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url)
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        response2 = self.client.get(url)
        self.assertEqual(response2["RH-Cache"], "hit (auth)")

    def test_cache_hit_includes_header_for_anonymous_user(self):
        url = reverse("feed_v3-list")

        response1 = self.client.get(url)
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url)
        self.assertEqual(response2["RH-Cache"], "hit")

    def test_cache_miss_includes_header(self):
        url = reverse("feed_v3-list")

        response = self.client.get(url)
        self.assertEqual(response["RH-Cache"], "miss")

    def test_cache_key_differs_by_feed_view(self):
        url = reverse("feed_v3-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "popular"})
        self.assertEqual(response1["RH-Cache"], "miss (auth)")

        response2 = self.client.get(url, {"feed_view": "following"})
        self.assertEqual(response2["RH-Cache"], "miss (auth)")

        response3 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response3["RH-Cache"], "miss (auth)")

        response4 = self.client.get(url, {"feed_view": "popular"})
        self.assertEqual(response4["RH-Cache"], "hit (auth)")

    def test_cache_key_differs_by_ordering(self):
        url = reverse("feed_v3-list")

        response1 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"ordering": "hot_score"})
        self.assertEqual(response2["RH-Cache"], "miss")

        response3 = self.client.get(url, {"ordering": "hot_score_v2"})
        self.assertEqual(response3["RH-Cache"], "hit")

    def test_cache_key_differs_by_hub_slug(self):
        url = reverse("feed_v3-list")
        hub2 = Hub.objects.create(name="Another Hub", slug="another-hub")

        response1 = self.client.get(url, {"hub_slug": self.hub.slug})
        self.assertEqual(response1["RH-Cache"], "miss")

        response2 = self.client.get(url, {"hub_slug": hub2.slug})
        self.assertEqual(response2["RH-Cache"], "miss")

        response3 = self.client.get(url, {"hub_slug": self.hub.slug})
        self.assertEqual(response3["RH-Cache"], "hit")

    def test_cache_key_includes_v3_feed_type(self):
        url = reverse("feed_v3-list")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        cache_keys = list(cache._cache.keys())
        v3_keys = [key for key in cache_keys if "v3_" in str(key)]
        self.assertGreater(len(v3_keys), 0)

    @patch("feed.views.feed_view_mixin.cache")
    def test_following_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("feed_v3-list")
        self.client.force_authenticate(user=self.user)

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "following"})

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

    @patch("feed.views.feed_view_mixin.cache")
    def test_personalized_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("feed_v3-list")
        self.client.force_authenticate(user=self.user)

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "personalized"})

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

    @patch("feed.views.feed_view_mixin.cache")
    def test_popular_feed_respects_use_cache_config(self, mock_cache):
        url = reverse("feed_v3-list")

        mock_cache.get.return_value = None

        self.client.get(url, {"feed_view": "popular"})

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)
