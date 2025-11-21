from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from analytics.constants.event_types import PAGE_VIEW
from analytics.models import UserInteractions
from analytics.tests.helpers import create_prefetched_paper
from personalize.services.sync_service import SyncService
from researchhub_document.helpers import create_post

User = get_user_model()


class SyncServiceTests(TestCase):
    @patch("personalize.services.sync_service.SyncClient")
    def test_sync_item_calls_sync_client_with_api_format(self, MockSyncClient):
        mock_client = Mock()
        mock_client.put_items.return_value = {
            "success": True,
            "synced": 1,
            "failed": 0,
            "errors": [],
        }

        service = SyncService(sync_client=mock_client)
        paper = create_prefetched_paper(title="Test Paper")

        result = service.sync_item(paper)

        mock_client.put_items.assert_called_once()
        call_args = mock_client.put_items.call_args[0][0]

        self.assertEqual(len(call_args), 1)
        api_item = call_args[0]

        self.assertIn("itemId", api_item)
        self.assertIn("properties", api_item)
        self.assertNotIn("ITEM_ID", api_item)

        self.assertEqual(result["success"], True)
        self.assertEqual(result["synced"], 1)

    def test_build_interaction_event_excludes_impression_when_recommendation_id_set(
        self,
    ):
        """Test that impression is not sent when recommendationId is present"""
        user = User.objects.create_user(
            username="testuser", email="test@researchhub.com"
        )
        post = create_post(created_by=user)
        content_type = ContentType.objects.get_for_model(post)

        interaction = UserInteractions.objects.create(
            user=user,
            event=PAGE_VIEW,
            unified_document=post.unified_document,
            content_type=content_type,
            object_id=post.id,
            event_timestamp=timezone.now(),
            impression="123|456|789",
            personalize_rec_id="rec-123",
        )

        service = SyncService()
        event = service._build_interaction_event(interaction)

        # recommendationId should be present
        self.assertIn("recommendationId", event)
        self.assertEqual(event["recommendationId"], "rec-123")

        # impression should NOT be present
        self.assertNotIn("impression", event)

    def test_build_interaction_event_includes_impression_when_no_recommendation_id(
        self,
    ):
        """Test that impression is sent when recommendationId is not present"""
        user = User.objects.create_user(
            username="testuser2", email="test2@researchhub.com"
        )
        post = create_post(created_by=user)
        content_type = ContentType.objects.get_for_model(post)

        interaction = UserInteractions.objects.create(
            user=user,
            event=PAGE_VIEW,
            unified_document=post.unified_document,
            content_type=content_type,
            object_id=post.id,
            event_timestamp=timezone.now(),
            impression="123|456|789",
            personalize_rec_id=None,
        )

        service = SyncService()
        event = service._build_interaction_event(interaction)

        # impression should be present
        self.assertIn("impression", event)
        self.assertEqual(event["impression"], ["123", "456", "789"])

        # recommendationId should NOT be present
        self.assertNotIn("recommendationId", event)

    def test_build_interaction_event_excludes_both_when_neither_set(self):
        """Test that neither field is present when both are empty"""
        user = User.objects.create_user(
            username="testuser3", email="test3@researchhub.com"
        )
        post = create_post(created_by=user)
        content_type = ContentType.objects.get_for_model(post)

        interaction = UserInteractions.objects.create(
            user=user,
            event=PAGE_VIEW,
            unified_document=post.unified_document,
            content_type=content_type,
            object_id=post.id,
            event_timestamp=timezone.now(),
            impression=None,
            personalize_rec_id=None,
        )

        service = SyncService()
        event = service._build_interaction_event(interaction)

        # Neither should be present
        self.assertNotIn("impression", event)
        self.assertNotIn("recommendationId", event)
