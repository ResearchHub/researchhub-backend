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


class PopularFeedTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("popular_test_user")

        self.hub1 = Hub.objects.create(name="Hub 1", slug="hub-1")
        self.hub2 = Hub.objects.create(name="Hub 2", slug="hub-2")

        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        self.high_score_paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.high_score_paper_doc.hubs.add(self.hub1)
        self.high_score_paper = Paper.objects.create(
            title="High Score Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.high_score_paper_doc,
        )

        self.medium_score_post_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="POST"
        )
        self.medium_score_post_doc.hubs.add(self.hub1)
        self.medium_score_post = ResearchhubPost.objects.create(
            title="Medium Score Post",
            document_type="POST",
            created_by=self.user,
            unified_document=self.medium_score_post_doc,
        )

        self.low_score_paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.low_score_paper_doc.hubs.add(self.hub2)
        self.low_score_paper = Paper.objects.create(
            title="Low Score Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.low_score_paper_doc,
        )

        self.high_score_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.high_score_paper.id,
            unified_document=self.high_score_paper_doc,
            hot_score=100,
            hot_score_v2=200,
            content={},
            metrics={},
        )
        self.high_score_entry.hubs.add(self.hub1)

        self.medium_score_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.post_content_type,
            object_id=self.medium_score_post.id,
            unified_document=self.medium_score_post_doc,
            hot_score=50,
            hot_score_v2=100,
            content={},
            metrics={},
        )
        self.medium_score_entry.hubs.add(self.hub1)

        self.low_score_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.low_score_paper.id,
            unified_document=self.low_score_paper_doc,
            hot_score=10,
            hot_score_v2=20,
            content={},
            metrics={},
        )
        self.low_score_entry.hubs.add(self.hub2)

    def tearDown(self):
        cache.clear()

    def test_unauthenticated_user_gets_results(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 3)

    def test_authenticated_user_gets_results(self):
        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 3)

    def test_popular_returns_all_entries(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(self.high_score_paper.id, result_ids)
        self.assertIn(self.medium_score_post.id, result_ids)
        self.assertIn(self.low_score_paper.id, result_ids)

    def test_popular_with_hub_slug_filters_correctly(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url, {"feed_view": "popular", "hub_slug": "hub-1"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(self.high_score_paper.id, result_ids)
        self.assertIn(self.medium_score_post.id, result_ids)
        self.assertNotIn(self.low_score_paper.id, result_ids)

    def test_popular_with_invalid_hub_slug_returns_empty(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "hub_slug": "nonexistent-hub"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_popular_orders_by_hot_score_v2(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score_v2"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 3)

        if len(results) >= 2:
            first_score = results[0].get("hot_score_v2", 0)
            second_score = results[1].get("hot_score_v2", 0)
            self.assertGreaterEqual(first_score, second_score)

    def test_popular_orders_by_hot_score(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 3)

        result_ids = [r["content_object"]["id"] for r in results]
        high_index = result_ids.index(self.high_score_paper.id)
        low_index = result_ids.index(self.low_score_paper.id)
        self.assertLess(high_index, low_index)

    def test_popular_defaults_to_hot_score_v2(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)

        if len(results) >= 2:
            first_score = results[0].get("hot_score_v2", 0)
            second_score = results[1].get("hot_score_v2", 0)
            self.assertGreaterEqual(first_score, second_score)

    def test_popular_rejects_latest_ordering(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url, {"feed_view": "popular", "ordering": "latest"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)

        if len(results) >= 2:
            first_score = results[0].get("hot_score_v2", 0)
            second_score = results[1].get("hot_score_v2", 0)
            self.assertGreaterEqual(first_score, second_score)

    def test_feed_content_type_filtering(self):
        url = reverse("researchhub_feed-list")

        # Arrange

        # Act
        popular_response = self.client.get(url, {"feed_view": "popular"})

        # Assert
        popular_result_ids = [
            r["content_object"]["id"] for r in popular_response.data["results"]
        ]
        popular_content_types = [
            r["content_type"] for r in popular_response.data["results"]
        ]

        self.assertIn(self.high_score_paper.id, popular_result_ids)
        self.assertIn(self.medium_score_post.id, popular_result_ids)
        self.assertIn("PAPER", popular_content_types)
        self.assertIn("RESEARCHHUBPOST", popular_content_types)
