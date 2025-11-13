from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from feed.services import PersonalizeFeedService
from hub.models import Hub
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_default_user


class PersonalizeFeedServiceTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_random_default_user("service_test_user")
        self.other_user = create_random_default_user("other_service_user")
        self.mock_client = Mock()

    def tearDown(self):
        cache.clear()

    def _create_sample_feed_entries(self, count=10):
        hub = Hub.objects.create(
            name="Test Hub", slug=f"test-hub-{timezone.now().timestamp()}"
        )
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)

        entries = []
        for i in range(count):
            unified_doc = ResearchhubUnifiedDocument.objects.create(
                document_type="POST"
            )
            unified_doc.hubs.add(hub)

            post = ResearchhubPost.objects.create(
                title=f"Test Post {i}",
                document_type="POST",
                created_by=self.user,
                unified_document=unified_doc,
            )

            feed_entry = FeedEntry.objects.create(
                action="PUBLISH",
                action_date=timezone.now(),
                content_type=post_content_type,
                object_id=post.id,
                unified_document=unified_doc,
                content={},
                metrics={},
            )
            feed_entry.hubs.add(hub)
            entries.append(feed_entry)

        return entries

    @patch(
        "feed.clients.personalize_client.PersonalizeClient.get_recommendations_for_user"
    )
    def test_get_queryset_uses_cache_on_second_call(self, mock_get_recommendations):
        entries = self._create_sample_feed_entries(count=3)
        doc_ids = [str(entry.unified_document_id) for entry in entries]
        mock_get_recommendations.return_value = doc_ids

        url = reverse("researchhub_feed-list")
        self.client.force_authenticate(user=self.user)

        response1 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response1.status_code, 200)
        self.assertIn("RH-Cache", response1)
        self.assertIn("partial-cache-miss", response1["RH-Cache"])
        self.assertEqual(mock_get_recommendations.call_count, 1)

        response2 = self.client.get(url, {"feed_view": "personalized"})
        self.assertEqual(response2.status_code, 200)
        self.assertIn("RH-Cache", response2)
        self.assertIn("partial-cache-hit", response2["RH-Cache"])
        self.assertEqual(mock_get_recommendations.call_count, 1)

    def test_get_queryset_preserves_personalize_order(self):
        entries = self._create_sample_feed_entries(count=10)

        reversed_ids = [str(entries[i].unified_document_id) for i in range(9, -1, -1)]
        self.mock_client.get_recommendations_for_user.return_value = reversed_ids

        service = PersonalizeFeedService(personalize_client=self.mock_client)
        result = service.get_queryset(user_id=self.user.id, filter_param="new-content")

        result_doc_ids = [entry.unified_document_id for entry in result]
        expected_ids = [int(id) for id in reversed_ids]
        self.assertEqual(result_doc_ids, expected_ids)

    def test_different_users_get_different_recommendations(self):
        self.mock_client.get_recommendations_for_user.side_effect = [
            ["1", "2", "3"],
            ["4", "5", "6"],
        ]

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        service.get_queryset(user_id=self.user.id, filter_param="new-content")

        service.get_queryset(user_id=self.other_user.id, filter_param="new-content")

        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 2)

    def test_different_filters_get_different_cache_keys(self):
        self.mock_client.get_recommendations_for_user.return_value = ["1", "2", "3"]

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        service.get_queryset(user_id=self.user.id, filter_param="new-content")
        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 1)

        service.get_queryset(user_id=self.user.id, filter_param="trending")
        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 2)

    def test_different_users_get_different_cache_keys(self):
        self.mock_client.get_recommendations_for_user.return_value = ["1", "2", "3"]

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        service.get_queryset(user_id=self.user.id, filter_param="new-content")

        service.get_queryset(user_id=self.other_user.id, filter_param="new-content")

        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 2)

    def test_cache_isolation_between_users(self):
        self.mock_client.get_recommendations_for_user.side_effect = [
            ["1", "2", "3"],
            ["4", "5", "6"],
        ]

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        service.get_queryset(user_id=self.user.id, filter_param="new-content")

        service.get_queryset(user_id=self.other_user.id, filter_param="new-content")

        service.get_queryset(user_id=self.user.id, filter_param="new-content")

        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 2)

    def test_force_refresh_bypasses_cache(self):
        self.mock_client.get_recommendations_for_user.return_value = ["1", "2", "3"]

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        service.get_queryset(user_id=self.user.id, filter_param="new-content")
        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 1)

        service.get_queryset(
            user_id=self.user.id, filter_param="new-content", force_refresh=True
        )
        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 2)

    def test_force_refresh_updates_cache_with_new_results(self):
        self.mock_client.get_recommendations_for_user.return_value = ["1", "2", "3"]

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        service.get_queryset(user_id=self.user.id, filter_param="new-content")

        self.mock_client.get_recommendations_for_user.return_value = ["4", "5", "6"]

        service.get_queryset(
            user_id=self.user.id, filter_param="new-content", force_refresh=True
        )

        self.mock_client.get_recommendations_for_user.return_value = ["7", "8", "9"]
        service.get_queryset(user_id=self.user.id, filter_param="new-content")

        self.assertEqual(self.mock_client.get_recommendations_for_user.call_count, 2)

    @patch(
        "feed.services.personalize_feed_service.PERSONALIZE_CONFIG",
        {
            "default_filter": "new-content",
            "cache_timeout": 3600,
            "num_results": 200,
        },
    )
    def test_cache_timeout_is_configurable(self):
        self.mock_client.get_recommendations_for_user.return_value = ["1", "2", "3"]

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        with patch("feed.services.personalize_feed_service.cache") as mock_cache:
            mock_cache.get.return_value = None

            service.get_queryset(user_id=self.user.id, filter_param="new-content")

            mock_cache.set.assert_called_once()
            call_args = mock_cache.set.call_args
            self.assertEqual(call_args[1]["timeout"], 3600)

    def test_personalize_api_error_raises_exception(self):
        self.mock_client.get_recommendations_for_user.side_effect = Exception(
            "AWS Error"
        )

        service = PersonalizeFeedService(personalize_client=self.mock_client)

        with self.assertRaises(Exception):
            service.get_queryset(user_id=self.user.id, filter_param="new-content")

    def test_personalize_returns_empty_list(self):
        self.mock_client.get_recommendations_for_user.return_value = []

        service = PersonalizeFeedService(personalize_client=self.mock_client)
        result = service.get_queryset(user_id=self.user.id, filter_param="new-content")

        self.assertEqual(len(result), 0)

    def test_personalize_returns_non_existent_ids_filters_them_out(self):
        entries = self._create_sample_feed_entries(count=10)

        valid_ids = [
            str(entries[0].unified_document_id),
            str(entries[1].unified_document_id),
        ]
        invalid_ids = ["99999", "88888"]
        self.mock_client.get_recommendations_for_user.return_value = (
            valid_ids + invalid_ids
        )

        service = PersonalizeFeedService(personalize_client=self.mock_client)
        result = service.get_queryset(user_id=self.user.id, filter_param="new-content")

        self.assertEqual(len(result), 2)
        result_doc_ids = {entry.unified_document_id for entry in result}
        expected_doc_ids = {
            entries[0].unified_document_id,
            entries[1].unified_document_id,
        }
        self.assertEqual(result_doc_ids, expected_doc_ids)

    def test_handles_none_from_cache_forces_personalize_call(self):
        with patch("feed.services.personalize_feed_service.cache") as mock_cache:
            mock_cache.get.return_value = None
            self.mock_client.get_recommendations_for_user.return_value = ["1", "2", "3"]

            service = PersonalizeFeedService(personalize_client=self.mock_client)
            service.get_queryset(user_id=self.user.id, filter_param="new-content")

            self.assertEqual(
                self.mock_client.get_recommendations_for_user.call_count, 1
            )
