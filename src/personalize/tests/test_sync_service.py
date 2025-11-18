from unittest.mock import Mock, patch

from django.test import TestCase

from analytics.tests.helpers import create_prefetched_paper
from personalize.services.sync_service import SyncService


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
