from unittest.mock import patch

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
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 3)

    def test_authenticated_user_gets_results(self):
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 3)

    def test_popular_returns_all_entries(self):
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(self.high_score_paper.id, result_ids)
        self.assertIn(self.medium_score_post.id, result_ids)
        self.assertIn(self.low_score_paper.id, result_ids)

    def test_popular_with_hub_slug_filters_correctly(self):
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular", "hub_slug": "hub-1"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(self.high_score_paper.id, result_ids)
        self.assertIn(self.medium_score_post.id, result_ids)
        self.assertNotIn(self.low_score_paper.id, result_ids)

    def test_popular_with_invalid_hub_slug_returns_empty(self):
        url = reverse("feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "hub_slug": "nonexistent-hub"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_popular_orders_by_hot_score_v2(self):
        url = reverse("feed-list")

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
        url = reverse("feed-list")

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

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_defaults_to_aws_trending(self, mock_get_trending):
        """Test that popular feed defaults to aws_trending ordering."""
        doc_ids = [
            self.high_score_entry.unified_document_id,
            self.medium_score_entry.unified_document_id,
            self.low_score_entry.unified_document_id,
        ]
        mock_get_trending.return_value = {
            "item_ids": doc_ids,
            "recommendation_id": "test-trending-id",
        }
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_trending.assert_called_once()
        self.assertEqual(response.get("RH-Feed-Source"), "aws-trending")

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_rejects_latest_ordering(self, mock_get_trending):
        """Test that invalid ordering falls back to default (aws_trending)."""
        # Return entries in expected order (high to low score)
        doc_ids = [
            self.high_score_entry.unified_document_id,
            self.medium_score_entry.unified_document_id,
            self.low_score_entry.unified_document_id,
        ]
        mock_get_trending.return_value = {
            "item_ids": doc_ids,
            "recommendation_id": "test-trending-id",
        }

        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular", "ordering": "latest"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should fallback to aws_trending (default)
        mock_get_trending.assert_called_once()
        self.assertEqual(response.get("RH-Feed-Source"), "aws-trending")

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_feed_content_type_filtering(self, mock_get_trending):
        doc_ids = [
            self.high_score_entry.unified_document_id,
            self.medium_score_entry.unified_document_id,
            self.low_score_entry.unified_document_id,
        ]
        mock_get_trending.return_value = {
            "item_ids": doc_ids,
            "recommendation_id": "test-trending-id",
        }

        url = reverse("feed-list")

        popular_response = self.client.get(url, {"feed_view": "popular"})

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

    def test_popular_with_hot_score_v2_ordering_skips_aws(self):
        url = reverse("feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score_v2"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have RH-Feed-Source header as "rh-popular"
        self.assertEqual(response.get("RH-Feed-Source"), "rh-popular")

    def test_popular_with_hot_score_ordering_skips_aws(self):
        url = reverse("feed-list")

        response = self.client.get(
            url, {"feed_view": "popular", "ordering": "hot_score"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.get("RH-Feed-Source"), "rh-popular")

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_fallback_on_aws_error(self, mock_get_trending):
        mock_get_trending.side_effect = Exception("AWS Error")
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.get("RH-Feed-Source"), "rh-popular")
        # Results should still be returned, ordered by hot_score_v2
        self.assertGreaterEqual(len(response.data["results"]), 1)

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_fallback_on_empty_trending_ids(self, mock_get_trending):
        mock_get_trending.return_value = {"item_ids": [], "recommendation_id": None}
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.get("RH-Feed-Source"), "rh-popular")

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_x_feed_source_header_aws(self, mock_get_trending):
        doc_ids = [
            self.high_score_entry.unified_document_id,
            self.medium_score_entry.unified_document_id,
            self.low_score_entry.unified_document_id,
        ]
        mock_get_trending.return_value = {
            "item_ids": doc_ids,
            "recommendation_id": "test-trending-id",
        }
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.get("RH-Feed-Source"), "aws-trending")

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_trending_preserves_aws_order(self, mock_get_trending):
        ordered_doc_ids = [
            self.low_score_entry.unified_document_id,
            self.medium_score_entry.unified_document_id,
            self.high_score_entry.unified_document_id,
        ]
        mock_get_trending.return_value = {
            "item_ids": ordered_doc_ids,
            "recommendation_id": "test-trending-id",
        }
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        result_doc_ids = []
        for r in results:
            # unified_document_id may be at top level or nested in content_object
            doc_id = r.get("unified_document_id")
            if doc_id is None and "content_object" in r:
                doc_id = r["content_object"].get("unified_document_id")
            result_doc_ids.append(doc_id)

        # Verify order matches AWS response (low, medium, high)
        low_idx = result_doc_ids.index(self.low_score_entry.unified_document_id)
        medium_idx = result_doc_ids.index(self.medium_score_entry.unified_document_id)
        high_idx = result_doc_ids.index(self.high_score_entry.unified_document_id)
        self.assertLess(low_idx, medium_idx)
        self.assertLess(medium_idx, high_idx)

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_trending_pagination(self, mock_get_trending):
        # Create more entries for pagination testing
        doc_ids = []

        for i in range(50):
            doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
            doc.hubs.add(self.hub1)
            paper = Paper.objects.create(
                title=f"Pagination Paper {i}",
                paper_publish_date=timezone.now(),
                unified_document=doc,
            )
            entry = FeedEntry.objects.create(
                action="PUBLISH",
                action_date=timezone.now(),
                content_type=self.paper_content_type,
                object_id=paper.id,
                unified_document=doc,
                hot_score=i,
                hot_score_v2=i,
                content={},
                metrics={},
            )
            entry.hubs.add(self.hub1)
            doc_ids.append(doc.id)

        mock_get_trending.return_value = {
            "item_ids": doc_ids,
            "recommendation_id": "test-trending-id",
        }
        url = reverse("feed-list")

        def get_doc_ids(results):
            doc_ids = set()
            for r in results:
                doc_id = r.get("unified_document_id")
                if doc_id is None and "content_object" in r:
                    doc_id = r["content_object"].get("unified_document_id")
                if doc_id:
                    doc_ids.add(doc_id)
            return doc_ids

        # Get page 1
        response1 = self.client.get(url, {"feed_view": "popular", "page": 1})
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        page1_ids = get_doc_ids(response1.data["results"])

        # Get page 2
        response2 = self.client.get(url, {"feed_view": "popular", "page": 2})
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        page2_ids = get_doc_ids(response2.data["results"])

        # Pages should not overlap
        self.assertEqual(len(page1_ids & page2_ids), 0)

    @patch("feed.filtering.log_error")
    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_popular_fallback_logs_to_sentry(self, mock_get_trending, mock_log_error):
        """Test that AWS errors are logged to Sentry."""
        mock_get_trending.side_effect = Exception("AWS Connection Error")
        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "popular"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_log_error.assert_called_once()
        call_args = mock_log_error.call_args
        self.assertIn("AWS Personalize", call_args[1].get("message", ""))
