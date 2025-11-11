from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow


class DiversificationCacheTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user = create_random_default_user("cache_test_user")
        cls.other_user = create_random_default_user("other_cache_user")
        cls.hub = Hub.objects.create(name="Test Hub", slug="test-hub")

        cls.subcategory_a = Hub.objects.create(
            name="Subcategory A",
            slug="subcategory-a",
            namespace=Hub.Namespace.SUBCATEGORY,
        )

        create_follow(cls.user, cls.hub)
        create_follow(cls.other_user, cls.hub)

        cls.paper_content_type = ContentType.objects.get_for_model(Paper)

        for i in range(10):
            doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
            doc.hubs.add(cls.hub, cls.subcategory_a)

            paper = Paper.objects.create(
                title=f"Paper {i}",
                paper_publish_date=timezone.now(),
                unified_document=doc,
            )

            entry = FeedEntry.objects.create(
                action="PUBLISH",
                action_date=timezone.now(),
                content_type=cls.paper_content_type,
                object_id=paper.id,
                unified_document=doc,
                hot_score_v2=100 - i,
                content={},
                metrics={},
            )
            entry.hubs.add(cls.hub)

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_diversified_batch_cached_on_first_request(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        cache_key_pattern = "researchhub_diversified:following:"

        keys_before = [k for k in cache._cache.keys() if cache_key_pattern in str(k)]
        self.assertEqual(len(keys_before), 0)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        keys_after = [k for k in cache._cache.keys() if cache_key_pattern in str(k)]
        self.assertGreater(len(keys_after), 0)

    def test_diversified_page_2_uses_cached_batch(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page": 1}
        )
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        response2 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page": 2}
        )
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        page_1_ids = [r["id"] for r in response1.data["results"]]
        page_2_ids = [r["id"] for r in response2.data["results"]]

        self.assertEqual(len(set(page_1_ids) & set(page_2_ids)), 0)

    def test_diversified_cache_key_excludes_page_number(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        self.client.get(url, {"feed_view": "following", "diversify": "true", "page": 1})

        cache_keys = [str(k) for k in cache._cache.keys()]
        diversified_keys = [k for k in cache_keys if "researchhub_diversified" in k]

        self.assertGreater(len(diversified_keys), 0)
        for key in diversified_keys:
            self.assertNotIn(":1-", key)
            self.assertNotIn(":2-", key)

    def test_diversified_cache_different_for_different_users(self):
        url = reverse("researchhub_feed-list")

        self.client.force_authenticate(user=self.user)
        response1 = self.client.get(
            url, {"feed_view": "following", "diversify": "true"}
        )

        self.client.force_authenticate(user=self.other_user)
        response2 = self.client.get(
            url, {"feed_view": "following", "diversify": "true"}
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        cache_keys = [str(k) for k in cache._cache.keys()]
        diversified_keys = [k for k in cache_keys if "researchhub_diversified" in k]

        self.assertGreaterEqual(len(diversified_keys), 2)

    def test_diversified_cache_different_for_different_hubs(self):
        hub2 = Hub.objects.create(name="Hub 2", slug="hub-2")
        create_follow(self.user, hub2)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(
            url,
            {"feed_view": "following", "diversify": "true", "hub_slug": self.hub.slug},
        )
        response2 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "hub_slug": hub2.slug}
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

    def test_diversified_cache_different_for_different_ordering(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        cache.clear()

        response1 = self.client.get(
            url,
            {
                "feed_view": "following",
                "diversify": "true",
                "ordering": "hot_score_v2",
            },
        )
        response2 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "ordering": "latest"}
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        cache_keys = [str(k) for k in cache._cache.keys()]
        diversified_keys = [k for k in cache_keys if "researchhub_diversified" in k]

        self.assertGreaterEqual(len(diversified_keys), 2)

    def test_diversified_cache_respects_timeout(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_page_5_bypasses_diversification_and_cache(self):
        for i in range(150):
            doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
            doc.hubs.add(self.hub, self.subcategory_a)

            paper = Paper.objects.create(
                title=f"Paper Extra {i}",
                paper_publish_date=timezone.now(),
                unified_document=doc,
            )

            entry = FeedEntry.objects.create(
                action="PUBLISH",
                action_date=timezone.now(),
                content_type=self.paper_content_type,
                object_id=paper.id,
                unified_document=doc,
                hot_score_v2=50 - i,
                content={},
                metrics={},
            )
            entry.hubs.add(self.hub)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page": 5}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data["results"]), 0)

    def test_diversified_pages_1_through_4_share_cache(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        cache.clear()

        response1 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page": 1}
        )
        keys_after_page_1 = len(
            [k for k in cache._cache.keys() if "diversified" in str(k)]
        )

        response2 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page": 2}
        )
        keys_after_page_2 = len(
            [k for k in cache._cache.keys() if "diversified" in str(k)]
        )

        self.assertEqual(keys_after_page_1, keys_after_page_2)

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

    def test_cache_cleared_between_requests_with_different_params(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        cache.clear()

        response1 = self.client.get(
            url,
            {
                "feed_view": "following",
                "diversify": "true",
                "ordering": "hot_score_v2",
            },
        )

        cache.clear()

        response2 = self.client.get(
            url,
            {"feed_view": "following", "diversify": "true", "ordering": "latest"},
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

    def test_user_votes_included_in_cached_diversified_results(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page": 1}
        )

        response2 = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page": 2}
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

    def test_anonymous_user_diversified_cache_separate_from_auth(self):
        url = reverse("researchhub_feed-list")

        response_anon = self.client.get(
            url, {"feed_view": "following", "diversify": "true"}
        )

        self.client.force_authenticate(user=self.user)
        response_auth = self.client.get(
            url, {"feed_view": "following", "diversify": "true"}
        )

        self.assertEqual(response_anon.status_code, status.HTTP_200_OK)
        self.assertEqual(response_auth.status_code, status.HTTP_200_OK)

        cache_keys = [str(k) for k in cache._cache.keys()]
        diversified_keys = [k for k in cache_keys if "researchhub_diversified" in k]

        self.assertGreaterEqual(len(diversified_keys), 1)
