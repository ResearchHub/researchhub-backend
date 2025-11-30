from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from analytics.constants.event_types import UPVOTE
from analytics.models import UserInteractions
from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from personalize.config.settings import PERSONALIZE_CONFIG
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user
from user.views.follow_view_mixins import create_follow


class TestPersonalizedFeed(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("personalized_test_user")
        self.other_user = create_random_default_user("other_user")

        self.hub = Hub.objects.create(name="Test Hub", slug="test-hub")
        create_follow(self.user, self.hub)
        create_follow(self.other_user, self.hub)

        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        self.paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper_doc.hubs.add(self.hub)
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.paper_doc,
        )

        self.post_doc = ResearchhubUnifiedDocument.objects.create(document_type="POST")
        self.post_doc.hubs.add(self.hub)
        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            document_type="POST",
            created_by=self.user,
            unified_document=self.post_doc,
        )

        self.paper_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.paper_doc,
            content={},
            metrics={},
        )
        self.paper_entry.hubs.add(self.hub)

        self.post_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.post_content_type,
            object_id=self.post.id,
            unified_document=self.post_doc,
            content={},
            metrics={},
        )
        self.post_entry.hubs.add(self.hub)

        # Create 5 interactions for users to pass cold-start threshold
        self._create_interactions_for_user(self.user, 5)
        self._create_interactions_for_user(self.other_user, 5)

    def _create_interactions_for_user(self, user, count):
        """Helper to create interactions for cold-start threshold."""
        for i in range(count):
            doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
            doc.hubs.add(self.hub)
            paper = Paper.objects.create(
                title=f"Interaction Paper {user.id}_{i}",
                paper_publish_date=timezone.now(),
                unified_document=doc,
            )
            UserInteractions.objects.create(
                user=user,
                event=UPVOTE,
                unified_document=doc,
                content_type=self.paper_content_type,
                object_id=paper.id,
                event_timestamp=timezone.now(),
            )

    def tearDown(self):
        cache.clear()

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_trending_items"
    )
    def test_unauthenticated_user_gets_trending_results(self, mock_get_trending):
        """Unauthenticated users should get trending results for personalized feed."""
        mock_get_trending.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-trending-id",
        }

        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-trending")
        mock_get_trending.assert_called_once()

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_authenticated_user_gets_personalized_results(
        self, mock_get_recommendations
    ):
        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(mock_get_recommendations.called)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_feed_preserves_recommendation_order(
        self, mock_get_recommendations
    ):
        extra_docs = []
        extra_papers = []
        for i in range(5):
            doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
            doc.hubs.add(self.hub)
            paper = Paper.objects.create(
                title=f"Paper {i}",
                paper_publish_date=timezone.now(),
                unified_document=doc,
            )
            entry = FeedEntry.objects.create(
                action="PUBLISH",
                action_date=timezone.now(),
                content_type=self.paper_content_type,
                object_id=paper.id,
                unified_document=doc,
                content={},
                metrics={},
            )
            entry.hubs.add(self.hub)
            extra_docs.append(doc)
            extra_papers.append(paper)

        reversed_order = [
            extra_docs[4].id,
            extra_docs[2].id,
            extra_docs[0].id,
            extra_docs[3].id,
            extra_docs[1].id,
        ]
        mock_get_recommendations.return_value = {
            "item_ids": reversed_order,
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 5)

        result_paper_ids = [
            item["content_object"]["id"] for item in response.data["results"]
        ]
        expected_paper_ids = [
            extra_papers[4].id,
            extra_papers[2].id,
            extra_papers[0].id,
            extra_papers[3].id,
            extra_papers[1].id,
        ]
        self.assertEqual(result_paper_ids, expected_paper_ids)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_uses_new_content_filter_by_default(
        self, mock_get_recommendations
    ):
        mock_get_recommendations.return_value = {
            "item_ids": [],
            "recommendation_id": None,
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recommendations.assert_called_once()
        call_args = mock_get_recommendations.call_args
        self.assertEqual(call_args[1]["filter"], "new-content")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_filters_by_recommended_ids(self, mock_get_recommendations):
        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.paper.id
        )

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_handles_client_exception(self, mock_get_recommendations):
        mock_get_recommendations.side_effect = Exception("AWS Error")

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Service falls back to following feed on error (graceful degradation)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_requests_configured_num_results(
        self, mock_get_recommendations
    ):
        """Service requests num_results from PERSONALIZE_CONFIG for pagination."""
        mock_get_recommendations.return_value = {
            "item_ids": [],
            "recommendation_id": None,
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recommendations.assert_called_once()
        call_args = mock_get_recommendations.call_args
        self.assertEqual(call_args[1]["num_results"], PERSONALIZE_CONFIG["num_results"])

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_recs_are_throttled_when_force_refresh_header_is_true(
        self, mock_get_recommendations
    ):
        """Force refresh requests should be throttled at 5/min."""
        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        for i in range(5):
            response = self.client.get(
                url, {"feed_view": "personalized"}, HTTP_RH_FORCE_REFRESH="true"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 6th request should be throttled
        response = self.client.get(
            url, {"feed_view": "personalized"}, HTTP_RH_FORCE_REFRESH="true"
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_recs_are_not_throttled_when_force_refresh_header_is_absent(
        self, mock_get_recommendations
    ):
        """Requests without force refresh header should not be throttled."""
        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        # Make many requests without the header - none should be throttled
        for i in range(10):
            response = self.client.get(url, {"feed_view": "personalized"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalized_recs_are_not_throttled_when_force_refresh_header_is_false(
        self, mock_get_recommendations
    ):
        """Requests with force refresh header set to false should not be throttled."""
        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        # Make many requests with header=false - none should be throttled
        for i in range(10):
            response = self.client.get(
                url, {"feed_view": "personalized"}, HTTP_RH_FORCE_REFRESH="false"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_force_refresh_header_triggers_cache_bypass(self, mock_get_recommendations):
        """Force refresh header should bypass cache, resulting in partial-cache-miss."""
        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        # First request populates the cache
        response = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("partial-cache-miss", response["RH-Cache"])

        # Second request hits the cache
        response = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("partial-cache-hit", response["RH-Cache"])

        # Request with force-refresh header bypasses cache
        response = self.client.get(
            url, {"feed_view": "personalized"}, HTTP_RH_FORCE_REFRESH="true"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("partial-cache-miss", response["RH-Cache"])

    @patch("personalize.services.feed_service.FeedService.get_recommendation_ids")
    def test_force_refresh_header_absent_defaults_to_false(
        self, mock_get_recommendation_ids
    ):
        """Without force refresh header, force_refresh should default to False."""
        mock_get_recommendation_ids.return_value = []

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recommendation_ids.assert_called_once()
        call_kwargs = mock_get_recommendation_ids.call_args[1]
        self.assertFalse(call_kwargs["force_refresh"])

    @patch("personalize.services.feed_service.FeedService.get_recommendation_ids")
    def test_personalized_feed_handles_service_exception(
        self, mock_get_recommendation_ids
    ):
        mock_get_recommendation_ids.side_effect = Exception("Service Error")

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Falls back to following feed on service exception
        self.assertEqual(response["RH-Feed-Source"], "rh-following")

    @patch("personalize.services.feed_service.FeedService.get_recommendation_ids")
    def test_personalized_feed_includes_recommendation_id_on_items(
        self, mock_get_recommendation_ids
    ):
        # Arrange
        mock_get_recommendation_ids.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id-abc123",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(url, {"feed_view": "personalized"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        for item in response.data["results"]:
            self.assertEqual(item["recommendation_id"], "test-rec-id-abc123")

        self.assertNotIn("recommendation_id", response.data)

    @patch("personalize.services.feed_service.FeedService.get_recommendation_ids")
    def test_personalized_feed_filters_only_papers(self, mock_get_recommendation_ids):
        # Arrange
        mock_get_recommendation_ids.return_value = {
            "item_ids": [self.paper_doc.id, self.post_doc.id],
            "recommendation_id": "test-rec-id-xyz",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        # Act
        response = self.client.get(url, {"feed_view": "personalized"})

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        content_types = [r["content_type"] for r in response.data["results"]]

        self.assertIn(self.paper.id, result_ids)
        self.assertNotIn(self.post.id, result_ids)
        self.assertIn("PAPER", content_types)
        self.assertNotIn("RESEARCHHUBPOST", content_types)


class TestPersonalizedFeedColdStart(APITestCase):
    """
    Tests for cold-start handling in personalized feed.

    Strategy resolution happens in view layer:
    - Users with < 5 interactions get following feed (hot_score_v2)
    - Users with >= 5 interactions get Personalize recommendations
    """

    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("cold_start_test_user")

        self.hub = Hub.objects.create(name="Test Hub", slug="test-hub")
        create_follow(self.user, self.hub)

        self.paper_content_type = ContentType.objects.get_for_model(Paper)

        self.paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper_doc.hubs.add(self.hub)
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.paper_doc,
        )

        self.paper_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.paper_doc,
            hot_score_v2=100,
            content={},
            metrics={},
        )
        self.paper_entry.hubs.add(self.hub)

    def tearDown(self):
        cache.clear()

    def _create_interactions(self, user, count):
        """Helper to create multiple interactions for a user."""
        for i in range(count):
            doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
            doc.hubs.add(self.hub)
            paper = Paper.objects.create(
                title=f"Interaction Paper {i}",
                paper_publish_date=timezone.now(),
                unified_document=doc,
            )
            UserInteractions.objects.create(
                user=user,
                event=UPVOTE,
                unified_document=doc,
                content_type=self.paper_content_type,
                object_id=paper.id,
                event_timestamp=timezone.now(),
            )

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_trending_items"
    )
    def test_unauthenticated_user_gets_trending_results(self, mock_get_trending):
        """Unauthenticated users should get trending results for personalized feed."""
        mock_get_trending.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-trending-id",
        }

        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-trending")
        mock_get_trending.assert_called_once()

    def test_user_with_zero_interactions_gets_following_feed(self):
        """Users with 0 interactions should get following feed."""
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.paper.id
        )

    def test_user_with_four_interactions_gets_following_feed(self):
        """Users with 4 interactions (below threshold) should get following feed."""
        self._create_interactions(self.user, 4)

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_user_with_five_interactions_gets_personalize(
        self, mock_get_recommendations
    ):
        """Users with 5 interactions (at threshold) should get Personalize."""
        self._create_interactions(self.user, 5)

        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-personalize")
        self.assertTrue(mock_get_recommendations.called)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_user_with_ten_plus_interactions_gets_personalize(
        self, mock_get_recommendations
    ):
        """Users with 10+ interactions should get Personalize."""
        self._create_interactions(self.user, 10)

        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-personalize")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalize_error_falls_back_to_following(self, mock_get_recommendations):
        """If Personalize fails, should fall back to following feed."""
        self._create_interactions(self.user, 5)

        mock_get_recommendations.side_effect = Exception("AWS Error")

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")
        self.assertEqual(len(response.data["results"]), 1)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalize_empty_results_falls_back_to_following(
        self, mock_get_recommendations
    ):
        """If Personalize returns no results, should fall back to following feed."""
        self._create_interactions(self.user, 5)

        mock_get_recommendations.return_value = {
            "item_ids": [],
            "recommendation_id": None,
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_interaction_count_is_cached(self, mock_get_recommendations):
        """Interaction count should be cached to avoid repeated DB queries."""
        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        self._create_interactions(self.user, 3)

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        # First request
        response1 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response1["RH-Feed-Source"], "rh-following")

        # Add more interactions (but cache won't see them yet)
        self._create_interactions(self.user, 5)

        # Second request - should still use cached count
        response2 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response2["RH-Feed-Source"], "rh-following")

        # Clear cache and try again
        cache.clear()
        response3 = self.client.get(url, {"feed_view": "personalized"})
        # Now it should see the new interactions (total 8)
        self.assertEqual(response3["RH-Feed-Source"], "aws-personalize")


class TestPersonalizedFeedStrategyResolution(APITestCase):
    """
    Tests for the strategy resolution logic in the view layer.

    The view determines whether to route to personalized or following feed
    based on user's interaction count before the request reaches the filter.
    """

    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("strategy_test_user")

        self.hub = Hub.objects.create(name="Test Hub", slug="test-hub")
        create_follow(self.user, self.hub)

        self.paper_content_type = ContentType.objects.get_for_model(Paper)

        self.paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper_doc.hubs.add(self.hub)
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.paper_doc,
        )

        self.paper_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.paper_doc,
            hot_score_v2=100,
            content={},
            metrics={},
        )
        self.paper_entry.hubs.add(self.hub)

    def tearDown(self):
        cache.clear()

    def _create_interactions(self, user, count):
        """Helper to create interactions for a user."""
        for i in range(count):
            doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
            doc.hubs.add(self.hub)
            paper = Paper.objects.create(
                title=f"Interaction Paper {i}",
                paper_publish_date=timezone.now(),
                unified_document=doc,
            )
            UserInteractions.objects.create(
                user=user,
                event=UPVOTE,
                unified_document=doc,
                content_type=self.paper_content_type,
                object_id=paper.id,
                event_timestamp=timezone.now(),
            )

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_trending_items"
    )
    def test_strategy_returns_trending_for_unauthenticated(self, mock_get_trending):
        """Unauthenticated requests should resolve to trending strategy."""
        mock_get_trending.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-trending-id",
        }

        url = reverse("feed-list")

        response = self.client.get(url, {"feed_view": "personalized"})

        # Unauthenticated users get trending feed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-trending")
        mock_get_trending.assert_called_once()

    def test_strategy_returns_following_for_low_interactions(self):
        """Users with < 5 interactions should resolve to following strategy."""
        self._create_interactions(self.user, 3)

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_strategy_returns_personalized_for_sufficient_interactions(
        self, mock_get_recommendations
    ):
        """Users with >= 5 interactions should resolve to personalized strategy."""
        self._create_interactions(self.user, 5)

        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-personalize")
        self.assertTrue(mock_get_recommendations.called)

    def test_list_routes_to_following_when_strategy_is_following(self):
        """When strategy resolves to following, list() routes to following handler."""
        # No interactions = following strategy
        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        # Should get following feed results (paper from followed hub)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.paper.id
        )

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_list_routes_to_personalize_when_strategy_is_personalized(
        self, mock_get_recommendations
    ):
        """When strategy resolves to personalized, list() routes to Personalize."""
        self._create_interactions(self.user, 5)

        mock_get_recommendations.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-rec-id",
        }

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        # Should get Personalize results
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-personalize")
        self.assertTrue(mock_get_recommendations.called)

    @patch(
        "personalize.clients.recommendation_client.RecommendationClient"
        ".get_recommendations_for_user"
    )
    def test_personalize_error_sets_following_source(self, mock_get_recommendations):
        """When Personalize fails, fallback sets RH-Feed-Source to following."""
        self._create_interactions(self.user, 5)

        mock_get_recommendations.side_effect = Exception("AWS Error")

        url = reverse("feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        # Should fallback to following feed
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "rh-following")


class TestUnauthenticatedPersonalizedFeed(APITestCase):
    """Tests for unauthenticated users viewing personalized ('for you') feed."""

    def setUp(self):
        cache.clear()
        self.hub = Hub.objects.create(name="Test Hub", slug="test-hub")

        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        # Create test documents
        self.paper_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper_doc.hubs.add(self.hub)
        self.paper = Paper.objects.create(
            title="Test Paper",
            paper_publish_date=timezone.now(),
            unified_document=self.paper_doc,
        )

        self.paper_entry = FeedEntry.objects.create(
            action="PUBLISH",
            action_date=timezone.now(),
            content_type=self.paper_content_type,
            object_id=self.paper.id,
            unified_document=self.paper_doc,
            hot_score=100,
            hot_score_v2=200,
            content={},
            metrics={},
        )
        self.paper_entry.hubs.add(self.hub)

    def tearDown(self):
        cache.clear()

    def test_strategy_returns_trending_for_unauthenticated(self):
        """Unauthenticated users should resolve to 'trending' strategy."""
        from feed.views.feed_view import FeedViewSet

        view = FeedViewSet()

        class MockRequest:
            class MockUser:
                is_authenticated = False

            user = MockUser()

        strategy = view._resolve_personalized_feed_strategy(MockRequest())
        self.assertEqual(strategy, "trending")

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_unauthenticated_gets_trending_feed(self, mock_get_trending):
        """Unauthenticated users viewing personalized feed get AWS trending."""
        mock_get_trending.return_value = {
            "item_ids": [self.paper_doc.id],
            "recommendation_id": "test-trending-id",
        }

        url = reverse("feed-list")
        # No authentication - anonymous user

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["RH-Feed-Source"], "aws-trending")
        mock_get_trending.assert_called_once()

    @patch(
        "personalize.clients.recommendation_client"
        ".RecommendationClient.get_trending_items"
    )
    def test_unauthenticated_falls_back_to_popular_on_error(self, mock_get_trending):
        """When trending fails for unauthenticated users, fallback to rh-popular."""
        mock_get_trending.side_effect = Exception("AWS Error")

        url = reverse("feed-list")
        # No authentication - anonymous user

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Falls back to rh-popular on error
        self.assertEqual(response["RH-Feed-Source"], "rh-popular")
