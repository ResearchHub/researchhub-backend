from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from feed.feed_config import PERSONALIZE_CONFIG
from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user


class TestPersonalizedFeed(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("personalized_test_user")
        self.other_user = create_random_default_user("other_user")

        self.hub = Hub.objects.create(name="Test Hub", slug="test-hub")

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

    def tearDown(self):
        cache.clear()

    def test_unauthenticated_without_user_id_gets_unfiltered(self):
        url = reverse("researchhub_feed-list")

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 2)

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_authenticated_user_gets_personalized_results(
        self, mock_get_recommendations
    ):
        mock_get_recommendations.return_value = [str(self.paper_entry.id)]

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(mock_get_recommendations.called)

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
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
            str(extra_docs[4].id),
            str(extra_docs[2].id),
            str(extra_docs[0].id),
            str(extra_docs[3].id),
            str(extra_docs[1].id),
        ]
        mock_get_recommendations.return_value = reversed_order

        url = reverse("researchhub_feed-list")
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
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_with_user_id_param_overrides_auth(
        self, mock_get_recommendations
    ):
        mock_get_recommendations.return_value = [str(self.paper_entry.id)]

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(
            url, {"feed_view": "personalized", "user_id": str(self.other_user.id)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recommendations.assert_called_once()
        call_args = mock_get_recommendations.call_args
        self.assertEqual(call_args[1]["user_id"], str(self.other_user.id))

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_uses_new_content_filter_by_default(
        self, mock_get_recommendations
    ):
        mock_get_recommendations.return_value = []

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recommendations.assert_called_once()
        call_args = mock_get_recommendations.call_args
        self.assertEqual(call_args[1]["filter"], "new-content")

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_filters_by_recommended_ids(self, mock_get_recommendations):
        mock_get_recommendations.return_value = [
            str(self.paper_entry.unified_document_id)
        ]

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.paper.id
        )

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_handles_client_exception(self, mock_get_recommendations):
        mock_get_recommendations.side_effect = Exception("AWS Error")

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Service returns empty queryset on error (graceful degradation)
        self.assertEqual(len(response.data["results"]), 0)

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_requests_configured_num_results(
        self, mock_get_recommendations
    ):
        """Service requests num_results from PERSONALIZE_CONFIG for pagination."""
        mock_get_recommendations.return_value = []

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recommendations.assert_called_once()
        call_args = mock_get_recommendations.call_args
        self.assertEqual(call_args[1]["num_results"], PERSONALIZE_CONFIG["num_results"])

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_recs_are_throttled_when_force_refresh_header_is_true(
        self, mock_get_recommendations
    ):
        """Force refresh requests should be throttled at 5/min."""
        mock_get_recommendations.return_value = [str(self.paper_entry.id)]

        url = reverse("researchhub_feed-list")
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
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_recs_are_not_throttled_when_force_refresh_header_is_absent(
        self, mock_get_recommendations
    ):
        """Requests without force refresh header should not be throttled."""
        mock_get_recommendations.return_value = [str(self.paper_entry.id)]

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        # Make many requests without the header - none should be throttled
        for i in range(10):
            response = self.client.get(url, {"feed_view": "personalized"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_personalized_recs_are_not_throttled_when_force_refresh_header_is_false(
        self, mock_get_recommendations
    ):
        """Requests with force refresh header set to false should not be throttled."""
        mock_get_recommendations.return_value = [str(self.paper_entry.id)]

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        # Make many requests with header=false - none should be throttled
        for i in range(10):
            response = self.client.get(
                url, {"feed_view": "personalized"}, HTTP_RH_FORCE_REFRESH="false"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_force_refresh_header_triggers_cache_bypass(self, mock_get_recommendations):
        """Force refresh header should bypass cache, resulting in partial-cache-miss."""
        mock_get_recommendations.return_value = [str(self.paper_entry.id)]

        url = reverse("researchhub_feed-list")
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

    @patch("feed.services.PersonalizeFeedService.get_recommendation_ids")
    def test_force_refresh_header_absent_defaults_to_false(
        self, mock_get_recommendation_ids
    ):
        """Without force refresh header, force_refresh should default to False."""
        mock_get_recommendation_ids.return_value = []

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recommendation_ids.assert_called_once()
        call_kwargs = mock_get_recommendation_ids.call_args[1]
        self.assertFalse(call_kwargs["force_refresh"])

    @patch("feed.services.PersonalizeFeedService.get_recommendation_ids")
    def test_personalized_feed_handles_service_exception(
        self, mock_get_recommendation_ids
    ):
        mock_get_recommendation_ids.side_effect = Exception("Service Error")

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response = self.client.get(url, {"feed_view": "personalized"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)
