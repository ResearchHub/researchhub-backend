"""
Tests for MedRxiv client.
"""

from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

from paper.ingestion.clients.preprints.medrxiv import MedRxivClient, MedRxivConfig


class TestMedRxivClient(TestCase):
    """Test cases for MedRxiv client using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = MedRxivConfig()
        self.client = MedRxivClient(self.config)

    @patch.object(MedRxivClient, "fetch_with_retry")
    def test_fetch_recent_pagination(self, mock_fetch):
        """Test pagination handling in fetch_recent."""
        # First page response
        response1 = {
            "messages": [
                {
                    "status": "ok",
                    "cursor": 0,
                    "count": 100,
                    "total": "150",
                }
            ],
            "collection": [{"doi": f"10.1101/paper{i}"} for i in range(100)],
        }

        # Second page response
        response2 = {
            "messages": [
                {
                    "status": "ok",
                    "cursor": 100,
                    "count": 50,
                    "total": "150",
                }
            ],
            "collection": [{"doi": f"10.1101/paper{i}"} for i in range(100, 150)],
        }

        # Mock to return different responses
        mock_fetch.side_effect = [response1, response2]

        # Mock parse to simplify
        with patch.object(self.client, "process_page") as mock_process:
            mock_process.side_effect = [
                response1["collection"],
                response2["collection"],
            ]

            papers = self.client.fetch_recent(
                since=datetime(2025, 1, 1), until=datetime(2025, 1, 2)
            )

            # Should have fetched all 150 papers
            self.assertEqual(len(papers), 150)
            self.assertEqual(mock_fetch.call_count, 2)

            # Verify both calls used medrxiv server
            mock_fetch.assert_any_call("/details/medrxiv/2025-01-01/2025-01-02/0/json")
            mock_fetch.assert_any_call(
                "/details/medrxiv/2025-01-01/2025-01-02/100/json"
            )
