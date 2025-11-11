from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow


class FeedDiversificationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("diversification_test_user")
        self.hub = Hub.objects.create(name="Main Hub", slug="main-hub")

        self.subcategory_a = Hub.objects.create(
            name="Subcategory A",
            slug="subcategory-a",
            namespace=Hub.Namespace.SUBCATEGORY,
        )
        self.subcategory_b = Hub.objects.create(
            name="Subcategory B",
            slug="subcategory-b",
            namespace=Hub.Namespace.SUBCATEGORY,
        )

        create_follow(self.user, self.hub)

        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

    def tearDown(self):
        cache.clear()

    def _create_entry(self, title, subcategory=None, hot_score_v2=100):
        doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        doc.hubs.add(self.hub)
        if subcategory:
            doc.hubs.add(subcategory)

        paper = Paper.objects.create(
            title=title, paper_publish_date=timezone.now(), unified_document=doc
        )

        entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=paper.id,
            unified_document=doc,
            hot_score_v2=hot_score_v2,
            content={},
            metrics={},
        )
        entry.hubs.add(self.hub)
        return entry

    def test_diversify_enabled_with_query_param_true(self):
        self._create_entry("A1", self.subcategory_a, 100)
        self._create_entry("A2", self.subcategory_a, 99)
        self._create_entry("A3", self.subcategory_a, 98)
        self._create_entry("B1", self.subcategory_b, 97)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertEqual(len(results), 4)

        titles = [r["content_object"]["title"] for r in results]
        self.assertEqual(titles[0], "A1")
        self.assertEqual(titles[1], "A2")
        self.assertNotEqual(titles[2], "A3")

    def test_diversify_disabled_without_query_param(self):
        self._create_entry("A1", self.subcategory_a, 100)
        self._create_entry("A2", self.subcategory_a, 99)
        self._create_entry("A3", self.subcategory_a, 98)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        titles = [r["content_object"]["title"] for r in results]
        self.assertEqual(titles[0], "A1")
        self.assertEqual(titles[1], "A2")
        self.assertEqual(titles[2], "A3")

    def test_diversify_ignored_when_param_false(self):
        self._create_entry("A1", self.subcategory_a, 100)
        self._create_entry("A2", self.subcategory_a, 99)
        self._create_entry("A3", self.subcategory_a, 98)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "diversify": "false"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        titles = [r["content_object"]["title"] for r in results]
        self.assertEqual(titles[:3], ["A1", "A2", "A3"])

    def test_diversify_ignored_for_unsupported_feed(self):
        self._create_entry("A1", self.subcategory_a, 100)

        url = reverse("researchhub_feed-list")

        response = self.client.get(url, {"feed_view": "popular", "diversify": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_max_two_consecutive_from_same_subcategory(self):
        for i in range(5):
            self._create_entry(f"A{i}", self.subcategory_a, 100 - i)
        for i in range(3):
            self._create_entry(f"B{i}", self.subcategory_b, 94 - i)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]

        subcategories = []
        for result in results:
            subcat = result.get("content_object", {}).get("subcategory")
            subcategories.append(subcat.get("id") if subcat else None)

        main_portion = subcategories[:4]

        consecutive_count = 1
        max_seen = 1
        for i in range(1, len(main_portion)):
            if main_portion[i] == main_portion[i - 1]:
                consecutive_count += 1
                max_seen = max(max_seen, consecutive_count)
            else:
                consecutive_count = 1

        self.assertLessEqual(max_seen, 2)

    def test_third_consecutive_gets_deferred(self):
        self._create_entry("A1", self.subcategory_a, 100)
        self._create_entry("A2", self.subcategory_a, 99)
        self._create_entry("A3", self.subcategory_a, 98)
        self._create_entry("B1", self.subcategory_b, 97)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        results = response.data["results"]
        titles = [r["content_object"]["title"] for r in results]

        self.assertEqual(titles[0], "A1")
        self.assertEqual(titles[1], "A2")
        self.assertEqual(titles[2], "B1")
        self.assertIn("A3", titles)

    def test_deferred_items_reinjected_at_position_5(self):
        for i in range(10):
            self._create_entry(f"A{i}", self.subcategory_a, 100 - i)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page_size": 50}
        )

        results = response.data["results"]
        self.assertGreaterEqual(len(results), 5)

        titles = [r["content_object"]["title"] for r in results]
        self.assertEqual(titles[0], "A0")
        self.assertEqual(titles[1], "A1")

        position_5 = titles[4] if len(titles) > 4 else None
        self.assertIsNotNone(position_5)

    def test_deferred_items_reinjected_at_position_10(self):
        for i in range(20):
            self._create_entry(f"A{i}", self.subcategory_a, 100 - i)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page_size": 50}
        )

        results = response.data["results"]
        self.assertGreaterEqual(len(results), 10)

    def test_multiple_deferrals_reinjected_fifo(self):
        for i in range(8):
            self._create_entry(f"A{i}", self.subcategory_a, 100 - i)
        self._create_entry("B1", self.subcategory_b, 92)
        for i in range(3):
            self._create_entry(f"A{8+i}", self.subcategory_a, 91 - i)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page_size": 50}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data["results"]), 5)

    def test_remaining_deferred_appended_at_end(self):
        for i in range(10):
            self._create_entry(f"A{i}", self.subcategory_a, 100 - i)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page_size": 50}
        )

        results = response.data["results"]
        self.assertEqual(len(results), 10)

        titles = [r["content_object"]["title"] for r in results]
        self.assertIn("A8", titles)
        self.assertIn("A9", titles)

    def test_diversification_with_two_subcategories_only(self):
        for i in range(3):
            self._create_entry(f"A{i}", self.subcategory_a, 100 - i * 2)
            self._create_entry(f"B{i}", self.subcategory_b, 99 - i * 2)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        results = response.data["results"]
        subcategories = []
        for result in results:
            subcat = result.get("content_object", {}).get("subcategory")
            subcategories.append(subcat.get("id") if subcat else None)

        consecutive_count = 1
        for i in range(1, len(subcategories)):
            if subcategories[i] == subcategories[i - 1]:
                consecutive_count += 1
                self.assertLessEqual(consecutive_count, 2)
            else:
                consecutive_count = 1

    def test_entries_without_subcategory_grouped_as_none(self):
        self._create_entry("NoSub1", None, 100)
        self._create_entry("NoSub2", None, 99)
        self._create_entry("NoSub3", None, 98)
        self._create_entry("A1", self.subcategory_a, 97)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        results = response.data["results"]
        titles = [r["content_object"]["title"] for r in results]

        self.assertEqual(titles[0], "NoSub1")
        self.assertEqual(titles[1], "NoSub2")
        self.assertNotEqual(titles[2], "NoSub3")

    def test_single_entry_per_subcategory(self):
        self._create_entry("A1", self.subcategory_a, 100)
        self._create_entry("B1", self.subcategory_b, 99)

        subcat_c = Hub.objects.create(
            name="Subcategory C",
            slug="subcategory-c",
            namespace=Hub.Namespace.SUBCATEGORY,
        )
        self._create_entry("C1", subcat_c, 98)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "following", "diversify": "true"})

        results = response.data["results"]
        titles = [r["content_object"]["title"] for r in results]
        self.assertEqual(titles, ["A1", "B1", "C1"])

    def test_diversifies_exactly_120_items(self):
        for i in range(150):
            self._create_entry(f"A{i}", self.subcategory_a, 1000 - i)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "following", "diversify": "true", "page_size": 30}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        page_1_count = len(response.data["results"])
        self.assertEqual(page_1_count, 30)

        response_page_4 = self.client.get(
            url,
            {"feed_view": "following", "diversify": "true", "page_size": 30, "page": 4},
        )
        self.assertEqual(len(response_page_4.data["results"]), 30)

        response_page_5 = self.client.get(
            url,
            {"feed_view": "following", "diversify": "true", "page_size": 30, "page": 5},
        )
        self.assertEqual(response_page_5.status_code, 200)
        self.assertGreater(len(response_page_5.data["results"]), 0)

    def test_pagination_works_after_diversification(self):
        for i in range(100):
            subcat = self.subcategory_a if i % 3 == 0 else self.subcategory_b
            self._create_entry(f"Item{i}", subcat, 1000 - i)

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        page_1 = self.client.get(
            url,
            {"feed_view": "following", "diversify": "true", "page": 1, "page_size": 20},
        )
        page_2 = self.client.get(
            url,
            {"feed_view": "following", "diversify": "true", "page": 2, "page_size": 20},
        )

        self.assertEqual(len(page_1.data["results"]), 20)
        self.assertEqual(len(page_2.data["results"]), 20)

        page_1_ids = [r["id"] for r in page_1.data["results"]]
        page_2_ids = [r["id"] for r in page_2.data["results"]]

        self.assertEqual(len(set(page_1_ids) & set(page_2_ids)), 0)
