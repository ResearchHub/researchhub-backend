import json
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from analytics.constants.event_types import FEED_ITEM_IMPRESSION, PAGE_VIEW
from analytics.models import UserInteractions
from hub.models import Hub
from hub.tests.helpers import create_hub
from personalize.services.sync_service import SyncService
from personalize.tests.helpers import create_prefetched_paper
from researchhub_document.helpers import create_post

User = get_user_model()


class SyncServiceTests(TestCase):
    @patch("personalize.services.sync_service.SyncClient")
    def test_sync_item_by_id_syncs_recent_paper(self, MockSyncClient):
        """Recent papers (within 60 days) should be synced."""
        mock_client = Mock()
        mock_client.put_items.return_value = {
            "success": True,
            "synced": 1,
            "failed": 0,
            "errors": [],
        }

        recent_date = timezone.now() - timedelta(days=30)
        unified_doc = create_prefetched_paper(
            title="Recent Paper", paper_publish_date=recent_date
        )

        service = SyncService(sync_client=mock_client)
        result = service.sync_item_by_id(unified_doc.id)

        mock_client.put_items.assert_called_once()
        self.assertEqual(result["success"], True)
        self.assertEqual(result["synced"], 1)

    @patch("personalize.services.sync_service.SyncClient")
    def test_sync_item_by_id_skips_old_paper(self, MockSyncClient):
        """Papers older than 60 days should be skipped."""
        mock_client = Mock()

        old_date = timezone.now() - timedelta(days=90)
        unified_doc = create_prefetched_paper(
            title="Old Paper", paper_publish_date=old_date
        )

        service = SyncService(sync_client=mock_client)
        result = service.sync_item_by_id(unified_doc.id)

        mock_client.put_items.assert_not_called()
        self.assertEqual(result["success"], True)
        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["skipped"], 1)

    @patch("personalize.services.sync_service.SyncClient")
    def test_sync_item_by_id_always_syncs_posts(self, MockSyncClient):
        """Posts should always be synced regardless of date."""
        mock_client = Mock()
        mock_client.put_items.return_value = {
            "success": True,
            "synced": 1,
            "failed": 0,
            "errors": [],
        }

        user = User.objects.create_user(
            username="post_test_user", email="post_test@researchhub.com"
        )
        post = create_post(created_by=user)

        service = SyncService(sync_client=mock_client)
        result = service.sync_item_by_id(post.unified_document.id)

        mock_client.put_items.assert_called_once()
        self.assertEqual(result["success"], True)
        self.assertEqual(result["synced"], 1)

    @patch("personalize.services.sync_service.SyncClient")
    def test_sync_item_by_id_includes_hub_data(self, MockSyncClient):
        """Synced items should include hub IDs in the properties."""
        mock_client = Mock()
        mock_client.put_items.return_value = {
            "success": True,
            "synced": 1,
            "failed": 0,
            "errors": [],
        }

        # Create hubs with different namespaces
        category_hub = create_hub(name="Category Hub")
        category_hub.namespace = Hub.Namespace.CATEGORY
        category_hub.save()

        subcategory_hub = create_hub(name="Subcategory Hub")
        subcategory_hub.namespace = Hub.Namespace.SUBCATEGORY
        subcategory_hub.save()

        # Create paper with hubs
        unified_doc = create_prefetched_paper(
            title="Paper With Hubs",
            hubs=[category_hub, subcategory_hub],
        )

        service = SyncService(sync_client=mock_client)
        service.sync_item_by_id(unified_doc.id)

        # Verify hub data was sent
        mock_client.put_items.assert_called_once()
        call_args = mock_client.put_items.call_args[0][0]
        api_item = call_args[0]

        # Parse the properties JSON string
        properties = json.loads(api_item["properties"])

        # Verify hub IDs are included
        self.assertIn("hubIds", properties)
        hub_ids = properties["hubIds"].split("|")
        self.assertIn(str(category_hub.id), hub_ids)
        self.assertIn(str(subcategory_hub.id), hub_ids)

        # Verify hub L1/L2 are set
        self.assertEqual(properties["hubL1"], str(category_hub.id))
        self.assertEqual(properties["hubL2"], str(subcategory_hub.id))

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

    def test_sync_impression_event_uses_correct_weight(self):
        """Test that FEED_ITEM_IMPRESSION event uses weight of 0.2"""
        user = User.objects.create_user(
            username="impression_user", email="impression@researchhub.com"
        )
        post = create_post(created_by=user)

        interaction = UserInteractions.objects.create(
            user=user,
            event=FEED_ITEM_IMPRESSION,
            unified_document=post.unified_document,
            content_type=None,
            object_id=None,
            event_timestamp=timezone.now(),
            personalize_rec_id="rec-impression-123",
        )

        service = SyncService()
        event = service._build_interaction_event(interaction)

        # Check that event weight is 0.2
        self.assertEqual(event["eventValue"], 0.2)
        self.assertEqual(event["eventType"], FEED_ITEM_IMPRESSION)
        self.assertEqual(event["itemId"], str(post.unified_document.id))
