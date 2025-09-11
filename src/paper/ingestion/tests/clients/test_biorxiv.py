"""
Tests for BioRxiv client.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.ingestion.clients.biorxiv import BioRxivClient, BioRxivConfig, BioRxivCursor
from paper.ingestion.exceptions import FetchError


class TestBioRxivClient(TestCase):
    """Test cases for BioRxiv client using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = BioRxivConfig()
        self.client = BioRxivClient(self.config)

        # Sample API response
        self.sample_response = {
            "messages": [
                {
                    "status": "ok",
                    "category": "all",
                    "interval": "2025-01-01:2025-01-01",
                    "funder": "all",
                    "cursor": 0,
                    "count": 2,
                    "count_new_papers": "2",
                    "total": "57",
                }
            ],
            "collection": [
                {
                    "title": "Persistent DNA methylation paper",
                    "authors": "Gomez Cuautle, D. D.; Rossi, A. R.",
                    "author_corresponding": "Alberto Javier Ramos",
                    "author_corresponding_institution": "CONICET",
                    "doi": "10.1101/2024.12.31.630767",
                    "date": "2025-01-01",
                    "version": "1",
                    "type": "new results",
                    "license": "cc_no",
                    "category": "neuroscience",
                    "jatsxml": (
                        "https://www.biorxiv.org/content/early/2025/01/01/"
                        "2024.12.31.630767.source.xml"
                    ),
                    "abstract": "Epilepsy is a debilitating neurological disorder...",
                    "funder": "NA",
                    "published": "NA",
                    "server": "bioRxiv",
                },
                {
                    "title": "YX0798 CDK9 Inhibitor",
                    "authors": "Jiang, V.; Xue, Y.",
                    "author_corresponding": "Vivian Jiang",
                    "author_corresponding_institution": "MD Anderson",
                    "doi": "10.1101/2024.12.31.629756",
                    "date": "2025-01-01",
                    "version": "1",
                    "type": "new results",
                    "license": "cc_no",
                    "category": "cancer biology",
                    "jatsxml": (
                        "https://www.biorxiv.org/content/early/2025/01/01/"
                        "2024.12.31.629756.source.xml"
                    ),
                    "abstract": "Non-genetic transcription evolution...",
                    "funder": "NA",
                    "published": "10.1182/bloodadvances.2025016511",
                    "server": "bioRxiv",
                },
            ],
        }

    def test_config_defaults(self):
        """Test BioRxiv config has correct defaults."""
        config = BioRxivConfig()
        self.assertEqual(config.source_name, "biorxiv")
        self.assertEqual(config.base_url, "https://api.biorxiv.org")
        self.assertEqual(config.rate_limit, 1.0)
        self.assertEqual(config.page_size, 100)
        self.assertEqual(config.request_timeout, 45.0)

    @patch("requests.Session.get")
    def test_fetch_with_retry(self, mock_get):
        """Test fetch with retry logic."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = self.sample_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.client.fetch_with_retry(
            "/details/biorxiv/2025-01-01/2025-01-01/0/json"
        )

        self.assertEqual(result, self.sample_response)
        mock_get.assert_called_once()

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_basic(self, mock_fetch):
        """Test basic callback function creation and usage."""
        mock_fetch.return_value = self.sample_response

        # Create fetcher callback
        fetch_page = self.client.create_recent_papers_fetcher(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 1), server="biorxiv"
        )

        # Test first call
        response, next_cursor, has_more = fetch_page()

        self.assertEqual(len(response["collection"]), 2)
        self.assertEqual(response["collection"][0]["doi"], "10.1101/2024.12.31.630767")

        # Check cursor is encoded string
        self.assertIsInstance(next_cursor, str)
        decoded_cursor = BioRxivCursor.decode(next_cursor)
        self.assertEqual(decoded_cursor.position, 100)  # page_size = 100
        self.assertEqual(decoded_cursor.since_date, "2025-01-01")
        self.assertEqual(decoded_cursor.until_date, "2025-01-01")
        self.assertEqual(decoded_cursor.server, "biorxiv")

        self.assertFalse(
            has_more
        )  # total is 57, cursor 100 > 57, so has_more should be False

        mock_fetch.assert_called_once_with(
            "/details/biorxiv/2025-01-01/2025-01-01/0/json"
        )

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_automatic_progression(self, mock_fetch):
        """Test automatic cursor advancement with multiple calls."""
        # Create responses for multiple pages
        response1 = {
            "messages": [{"status": "ok", "cursor": 0, "count": 2, "total": "200"}],
            "collection": [{"doi": "10.1101/paper1"}, {"doi": "10.1101/paper2"}],
        }
        response2 = {
            "messages": [{"status": "ok", "cursor": 100, "count": 2, "total": "200"}],
            "collection": [{"doi": "10.1101/paper3"}, {"doi": "10.1101/paper4"}],
        }
        response3 = {
            "messages": [{"status": "ok", "cursor": 200, "count": 0, "total": "200"}],
            "collection": [],
        }

        mock_fetch.side_effect = [response1, response2, response3]

        # Create fetcher
        fetch_page = self.client.create_recent_papers_fetcher(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 1)
        )

        # First call - should start at cursor 0
        response1, cursor1, has_more1 = fetch_page()
        self.assertEqual(len(response1["collection"]), 2)
        self.assertIsInstance(cursor1, str)
        decoded1 = BioRxivCursor.decode(cursor1)
        self.assertEqual(decoded1.position, 100)
        self.assertTrue(has_more1)

        # Second call - should automatically advance to cursor 100
        response2_result, cursor2, has_more2 = fetch_page()
        self.assertEqual(len(response2_result["collection"]), 2)
        self.assertIsInstance(cursor2, str)
        decoded2 = BioRxivCursor.decode(cursor2)
        self.assertEqual(decoded2.position, 200)
        self.assertFalse(has_more2)  # cursor 200 >= total 200

        # Third call - should return empty since has_more is False
        response3_result, cursor3, has_more3 = fetch_page()
        self.assertEqual(response3_result, {})
        self.assertIsInstance(cursor3, str)
        decoded3 = BioRxivCursor.decode(cursor3)
        self.assertEqual(decoded3.position, 200)
        self.assertFalse(has_more3)

        # Verify correct endpoints were called
        expected_calls = [
            "/details/biorxiv/2025-01-01/2025-01-01/0/json",
            "/details/biorxiv/2025-01-01/2025-01-01/100/json",
        ]
        actual_calls = [call[0][0] for call in mock_fetch.call_args_list]
        self.assertEqual(actual_calls, expected_calls)

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_automatic_progression(self, mock_fetch):
        """Test automatic cursor progression functionality."""
        response1 = {
            "messages": [{"status": "ok", "cursor": 0, "count": 1, "total": "300"}],
            "collection": [{"doi": "10.1101/paper_at_0"}],
        }
        response2 = {
            "messages": [{"status": "ok", "cursor": 100, "count": 1, "total": "300"}],
            "collection": [{"doi": "10.1101/paper_at_100"}],
        }
        response3 = {
            "messages": [{"status": "ok", "cursor": 200, "count": 1, "total": "300"}],
            "collection": [{"doi": "10.1101/paper_at_200"}],
        }

        mock_fetch.side_effect = [response1, response2, response3]

        # Create fetcher
        fetch_page = self.client.create_recent_papers_fetcher()

        # First call - starts from position 0
        response1_result, cursor1, has_more1 = fetch_page()
        self.assertEqual(len(response1_result["collection"]), 1)
        self.assertEqual(response1_result["collection"][0]["doi"], "10.1101/paper_at_0")
        self.assertIsInstance(cursor1, str)
        decoded1 = BioRxivCursor.decode(cursor1)
        self.assertEqual(decoded1.position, 100)
        self.assertTrue(has_more1)

        # Second call - automatic progression to position 100
        response2_result, cursor2, has_more2 = fetch_page()
        self.assertEqual(len(response2_result["collection"]), 1)
        self.assertEqual(
            response2_result["collection"][0]["doi"], "10.1101/paper_at_100"
        )
        self.assertIsInstance(cursor2, str)
        decoded2 = BioRxivCursor.decode(cursor2)
        self.assertEqual(decoded2.position, 200)
        self.assertTrue(has_more2)

        # Third call - automatic progression to position 200
        response3_result, cursor3, has_more3 = fetch_page()
        self.assertEqual(len(response3_result["collection"]), 1)
        self.assertEqual(
            response3_result["collection"][0]["doi"], "10.1101/paper_at_200"
        )
        decoded3 = BioRxivCursor.decode(cursor3)
        self.assertEqual(decoded3.position, 300)
        self.assertFalse(has_more3)  # cursor 300 >= total 300

        # Verify endpoints - should use default date range (7 days)
        actual_calls = [call[0][0] for call in mock_fetch.call_args_list]
        self.assertEqual(len(actual_calls), 3)

        # Check that correct cursors were used (automatic progression)
        self.assertIn("/0/json", actual_calls[0])
        self.assertIn("/100/json", actual_calls[1])
        self.assertIn("/200/json", actual_calls[2])

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_server_parameter(self, mock_fetch):
        """Test fetcher works with different server parameter."""
        mock_fetch.return_value = self.sample_response

        # Create fetcher for MedRxiv
        fetch_page = self.client.create_recent_papers_fetcher(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 1), server="medrxiv"
        )

        response, cursor, has_more = fetch_page()

        # Verify it used medrxiv server
        mock_fetch.assert_called_once_with(
            "/details/medrxiv/2025-01-01/2025-01-01/0/json"
        )
        self.assertEqual(len(response["collection"]), 2)

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_empty_response(self, mock_fetch):
        """Test fetcher handles empty responses gracefully."""
        empty_response = {
            "messages": [{"status": "ok", "cursor": 0, "count": 0, "total": "0"}],
            "collection": [],
        }
        mock_fetch.return_value = empty_response

        fetch_page = self.client.create_recent_papers_fetcher()

        response, cursor, has_more = fetch_page()

        self.assertEqual(len(response["collection"]), 0)
        self.assertIsInstance(cursor, str)
        decoded = BioRxivCursor.decode(cursor)
        self.assertEqual(
            decoded.position, 0
        )  # position doesn't advance when collection is empty
        self.assertFalse(has_more)

        # Second call should still return empty
        response2, cursor2, has_more2 = fetch_page()
        self.assertEqual(response2, {})
        self.assertFalse(has_more2)

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_error_handling(self, mock_fetch):
        """Test fetcher propagates errors from fetch_with_retry."""

        mock_fetch.side_effect = FetchError("Network error")

        fetch_page = self.client.create_recent_papers_fetcher()

        with self.assertRaises(FetchError):
            fetch_page()

    def test_create_recent_papers_fetcher_default_dates(self):
        """Test fetcher uses default date range (last 7 days) when not specified."""
        with patch.object(self.client, "fetch_with_retry") as mock_fetch:
            mock_fetch.return_value = {"messages": [], "collection": []}

            fetch_page = self.client.create_recent_papers_fetcher()
            fetch_page()

            # Should have been called with date range from 7 days ago to today
            call_args = mock_fetch.call_args[0][0]
            self.assertTrue(call_args.startswith("/details/biorxiv/"))
            self.assertTrue(call_args.endswith("/0/json"))

            # Extract dates from endpoint
            parts = call_args.split("/")
            start_date = parts[3]  # Should be 7 days ago
            end_date = parts[4]  # Should be today

            # Verify dates are in correct format
            self.assertRegex(start_date, r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(end_date, r"^\d{4}-\d{2}-\d{2}$")

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_with_start_cursor(self, mock_fetch):
        """Test fetcher can be created with custom start cursor for resumption."""
        response1 = {
            "messages": [{"status": "ok", "cursor": 500, "count": 2, "total": "1000"}],
            "collection": [
                {"doi": "10.1101/paper_at_500"},
                {"doi": "10.1101/paper_at_501"},
            ],
        }
        response2 = {
            "messages": [{"status": "ok", "cursor": 600, "count": 1, "total": "1000"}],
            "collection": [{"doi": "10.1101/paper_at_600"}],
        }

        mock_fetch.side_effect = [response1, response2]

        # Create fetcher starting from cursor 500 (resumption scenario)
        start_cursor = BioRxivCursor(
            500, "2025-01-01", "2025-01-01", "biorxiv"
        ).encode()
        fetch_page = self.client.create_recent_papers_fetcher(
            since=datetime(2025, 1, 1),
            until=datetime(2025, 1, 1),
            start_cursor=start_cursor,
        )

        # First call should start from cursor 500
        response1, cursor1, has_more1 = fetch_page()
        self.assertEqual(len(response1["collection"]), 2)
        self.assertEqual(response1["collection"][0]["doi"], "10.1101/paper_at_500")
        self.assertIsInstance(cursor1, str)
        decoded1 = BioRxivCursor.decode(cursor1)
        self.assertEqual(decoded1.position, 600)
        self.assertTrue(has_more1)

        # Second call should automatically advance to cursor 600
        response2, cursor2, has_more2 = fetch_page()
        self.assertEqual(len(response2["collection"]), 1)
        self.assertEqual(response2["collection"][0]["doi"], "10.1101/paper_at_600")
        self.assertIsInstance(cursor2, str)
        decoded2 = BioRxivCursor.decode(cursor2)
        self.assertEqual(decoded2.position, 700)
        self.assertTrue(has_more2)

        # Verify endpoints called with correct cursors
        expected_calls = [
            "/details/biorxiv/2025-01-01/2025-01-01/500/json",
            "/details/biorxiv/2025-01-01/2025-01-01/600/json",
        ]
        actual_calls = [call[0][0] for call in mock_fetch.call_args_list]
        self.assertEqual(actual_calls, expected_calls)

    def test_biorxiv_cursor_encode_decode(self):
        """Test BioRxivCursor encoding and decoding."""
        # Create cursor
        cursor = BioRxivCursor(
            position=1500,
            since_date="2025-01-01",
            until_date="2025-01-31",
            server="biorxiv",
        )

        # Encode cursor
        encoded = cursor.encode()
        self.assertIsInstance(encoded, str)

        # Decode cursor
        decoded = BioRxivCursor.decode(encoded)
        self.assertEqual(decoded.position, 1500)
        self.assertEqual(decoded.since_date, "2025-01-01")
        self.assertEqual(decoded.until_date, "2025-01-31")
        self.assertEqual(decoded.server, "biorxiv")

    def test_biorxiv_cursor_invalid_decode(self):
        """Test BioRxivCursor handles invalid encoded strings."""
        with self.assertRaises(ValueError):
            BioRxivCursor.decode("invalid_base64!")

        with self.assertRaises(ValueError):
            BioRxivCursor.decode("dGVzdA==")  # "test" in base64, but not JSON

    @patch.object(BioRxivClient, "fetch_with_retry")
    def test_create_recent_papers_fetcher_with_encoded_cursor(self, mock_fetch):
        """Test fetcher can be created with encoded cursor string."""
        # Create original cursor
        original_cursor = BioRxivCursor(
            position=750,
            since_date="2025-01-15",
            until_date="2025-01-16",
            server="medrxiv",
        )
        encoded_cursor = original_cursor.encode()

        response1 = {
            "messages": [{"status": "ok", "cursor": 750, "count": 3, "total": "1200"}],
            "collection": [
                {"doi": "10.1101/paper750"},
                {"doi": "10.1101/paper751"},
                {"doi": "10.1101/paper752"},
            ],
        }
        mock_fetch.return_value = response1

        # Create fetcher with encoded cursor - must match cursor's date range
        fetch_page = self.client.create_recent_papers_fetcher(
            since=datetime(2025, 1, 15),
            until=datetime(2025, 1, 16),
            server="medrxiv",
            start_cursor=encoded_cursor,
        )

        # First call should use cursor's date range and server, not fetcher defaults
        response, next_cursor, has_more = fetch_page()

        self.assertEqual(len(response["collection"]), 3)
        self.assertEqual(response["collection"][0]["doi"], "10.1101/paper750")
        self.assertTrue(has_more)

        # Check the returned cursor has the correct info
        self.assertIsInstance(next_cursor, str)
        decoded = BioRxivCursor.decode(next_cursor)
        self.assertEqual(decoded.position, 850)  # 750 + 100
        self.assertEqual(decoded.since_date, "2025-01-15")
        self.assertEqual(decoded.until_date, "2025-01-16")
        self.assertEqual(decoded.server, "medrxiv")

        # Verify endpoint used cursor's date range and server
        mock_fetch.assert_called_once_with(
            "/details/medrxiv/2025-01-15/2025-01-16/750/json"
        )

    def test_create_recent_papers_fetcher_cursor_mismatch_error(self):
        """Test error is raised when cursor date range doesn't match fetcher."""
        # Create cursor with different date range
        cursor = BioRxivCursor(
            position=200,
            since_date="2025-02-01",  # Different from fetcher
            until_date="2025-02-02",  # Different from fetcher
            server="biorxiv",
        ).encode()

        # Create fetcher with specific dates, but pass cursor with different dates
        with self.assertRaises(ValueError) as cm:
            self.client.create_recent_papers_fetcher(
                since=datetime(2025, 1, 1),  # Different from cursor
                until=datetime(2025, 1, 31),  # Different from cursor
                start_cursor=cursor,
            )

        # Check error message contains mismatch info
        self.assertIn("Cursor date range mismatch", str(cm.exception))
