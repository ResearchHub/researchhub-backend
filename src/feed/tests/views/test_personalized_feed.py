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
