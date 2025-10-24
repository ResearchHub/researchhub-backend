"""
Tests for MedRxiv client.
"""

from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

from paper.ingestion.clients.medrxiv import MedRxivClient, MedRxivConfig


class TestMedRxivClient(TestCase):
    """Test cases for MedRxiv client using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = MedRxivConfig()
        self.client = MedRxivClient(self.config)

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
                    "total": "42",
                }
            ],
            "collection": [
                {
                    "title": "COVID-19 Clinical Trial Results",
                    "authors": "Smith, J.; Jones, A.",
                    "author_corresponding": "Jane Smith",
                    "author_corresponding_institution": "Harvard Medical School",
                    "doi": "10.1101/2025.01.01.25000001",
                    "date": "2025-01-01",
                    "version": "1",
                    "type": "new results",
                    "license": "cc_by",
                    "category": "infectious diseases",
                    "jatsxml": (
                        "https://www.medrxiv.org/content/early/2025/01/01/"
                        "2025.01.01.25000001.source.xml"
                    ),
                    "abstract": "A clinical trial of COVID-19 treatment...",
                    "funder": "NIH",
                    "published": "NA",
                    "server": "medrxiv",
                },
                {
                    "title": "Machine Learning in Medical Diagnostics",
                    "authors": "Chen, L.; Wang, M.",
                    "author_corresponding": "Li Chen",
                    "author_corresponding_institution": "Stanford Medical",
                    "doi": "10.1101/2025.01.01.25000002",
                    "date": "2025-01-01",
                    "version": "1",
                    "type": "new results",
                    "license": "cc_no",
                    "category": "health informatics",
                    "jatsxml": (
                        "https://www.medrxiv.org/content/early/2025/01/01/"
                        "2025.01.01.25000002.source.xml"
                    ),
                    "abstract": "Application of ML models in diagnostics...",
                    "funder": "NA",
                    "published": "10.1016/j.lancet.2025.01.001",
                    "server": "medrxiv",
                },
            ],
        }

    def test_config_defaults(self):
        """Test MedRxiv config has correct defaults."""
        config = MedRxivConfig()
        self.assertEqual(config.source_name, "medrxiv")
        self.assertEqual(config.base_url, "https://api.biorxiv.org")
        self.assertEqual(config.rate_limit, 1.0)
        self.assertEqual(config.page_size, 100)
        self.assertEqual(config.request_timeout, 45.0)

    def test_default_server(self):
        """Test MedRxiv client uses correct default server."""
        self.assertEqual(self.client.default_server, "medrxiv")

    def test_parse(self):
        """Test parsing of MedRxiv API response."""
        papers = self.client.parse(self.sample_response)

        self.assertEqual(len(papers), 2)

        # Check first paper
        paper1 = papers[0]
        self.assertEqual(paper1["doi"], "10.1101/2025.01.01.25000001")
        self.assertEqual(paper1["version"], "1")
        self.assertEqual(paper1["title"], "COVID-19 Clinical Trial Results")
        self.assertEqual(paper1["category"], "infectious diseases")
        self.assertEqual(paper1["server"], "medrxiv")
        self.assertEqual(paper1["date"], "2025-01-01")
        self.assertEqual(paper1["license"], "cc_by")

        # Check second paper (has published info)
        paper2 = papers[1]
        self.assertEqual(paper2["doi"], "10.1101/2025.01.01.25000002")
        self.assertEqual(paper2["published"], "10.1016/j.lancet.2025.01.001")
        self.assertEqual(paper2["category"], "health informatics")

    @patch("requests.Session.get")
    def test_fetch_with_retry(self, mock_get):
        """Test fetch with retry logic."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = self.sample_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.client.fetch_with_retry(
            "/details/medrxiv/2025-01-01/2025-01-01/0/json"
        )

        self.assertEqual(result, self.sample_response)
        mock_get.assert_called_once()

    @patch.object(MedRxivClient, "fetch_with_retry")
    def test_fetch_recent(self, mock_fetch):
        """Test fetching recent papers uses medrxiv server by default."""
        # Mock response - return empty list after first call to stop pagination
        mock_fetch.side_effect = [
            self.sample_response,
            {"messages": [], "collection": []},
        ]

        # Fetch papers without specifying server
        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 1)
        )

        # Check results
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0]["doi"], "10.1101/2025.01.01.25000001")

        # Verify endpoint was called with medrxiv server
        mock_fetch.assert_any_call("/details/medrxiv/2025-01-01/2025-01-01/0/json")

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
