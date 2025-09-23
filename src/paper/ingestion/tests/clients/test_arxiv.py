"""
Tests for ArXiv client.
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.ingestion.clients.arxiv import ArXivClient, ArXivConfig


class TestArXivClient(TestCase):
    """Test cases for ArXiv client using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = ArXivConfig()
        self.client = ArXivClient(self.config)

        # Load fixture files
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")

        with open(os.path.join(fixtures_dir, "arxiv_sample_response.xml"), "r") as f:
            self.sample_xml_response = f.read()

        with open(os.path.join(fixtures_dir, "arxiv_empty_response.xml"), "r") as f:
            self.empty_xml_response = f.read()

    def test_config_defaults(self):
        """Test ArXiv config has correct defaults."""
        config = ArXivConfig()
        self.assertEqual(config.source_name, "arxiv")
        self.assertEqual(
            config.base_url,
            "https://export.arxiv.org/api",
        )
        self.assertEqual(config.rate_limit, 0.33)  # 3 second delay
        self.assertEqual(config.page_size, 100)
        self.assertEqual(config.request_timeout, 30.0)
        self.assertEqual(config.max_results_per_query, 2000)

    def test_parse(self):
        """Test parsing of ArXiv Atom XML response."""
        papers = self.client.parse(self.sample_xml_response)

        self.assertEqual(len(papers), 2)

        # Check that papers contain raw XML
        paper1 = papers[0]
        self.assertIn("raw_xml", paper1)
        self.assertEqual(paper1["source"], "arxiv")

        # Verify the raw XML contains expected content
        self.assertIn("2509.08827v1", paper1["raw_xml"])
        self.assertIn(
            "A Survey of Reinforcement Learning for Large Reasoning Models",
            paper1["raw_xml"],
        )
        self.assertIn("Kaiyan Zhang", paper1["raw_xml"])
        self.assertIn("cs.CL", paper1["raw_xml"])

        # Check second paper
        paper2 = papers[1]
        self.assertIn("raw_xml", paper2)
        self.assertEqual(paper2["source"], "arxiv")
        self.assertIn("2509.08817v1", paper2["raw_xml"])
        self.assertIn("Quantum Cardinality", paper2["raw_xml"])
        self.assertIn("7 pages", paper2["raw_xml"])  # Comment field

    def test_parse_empty_response(self):
        """Test parsing empty XML response."""
        papers = self.client.parse(self.empty_xml_response)
        self.assertEqual(papers, [])

    def test_parse_invalid_xml(self):
        """Test parsing invalid XML returns empty list."""
        papers = self.client.parse("Invalid XML content")
        self.assertEqual(papers, [])

    @patch("requests.Session.get")
    def test_fetch_with_retry(self, mock_get):
        """Test fetch with retry logic."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.text = self.sample_xml_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.client.fetch_with_retry(
            "/query", {"search_query": "all:electron"}
        )

        self.assertEqual(result, self.sample_xml_response)
        mock_get.assert_called_once()

    @patch.object(ArXivClient, "fetch_with_retry")
    def test_fetch_recent(self, mock_fetch):
        """Test fetching recent papers."""
        # Mock response - return empty after first call to stop pagination
        mock_fetch.side_effect = [
            self.sample_xml_response,
            self.empty_xml_response,
        ]

        # Fetch papers
        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1),
            until=datetime(2025, 1, 7),
        )

        # Check results
        self.assertEqual(len(papers), 2)
        self.assertIn("raw_xml", papers[0])
        self.assertIn("2509.08827v1", papers[0]["raw_xml"])

        # Verify query was constructed correctly
        first_call_args = mock_fetch.call_args_list[0]
        params = first_call_args[0][1]  # Get params from first call
        self.assertEqual(
            params["search_query"], "lastUpdatedDate:[202501010000 TO 202501070000]"
        )

    def _create_test_response(self, start_idx, count, total=None):
        """Helper to create test XML responses."""
        response = '<?xml version="1.0" encoding="UTF-8"?>\n'
        response += '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        if total:
            response += (
                f"  <opensearch:totalResults "
                f'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
                f"{total}</opensearch:totalResults>\n"
            )

        for i in range(start_idx, start_idx + count):
            response += f"""  <entry>
    <id>http://arxiv.org/abs/2401.{i:05d}</id>
    <title>Paper {i}</title>
    <summary>Summary {i}</summary>
    <published>2025-01-01T00:00:00Z</published>
    <updated>2025-01-01T00:00:00Z</updated>
    <author><name>Author {i}</name></author>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
"""
        response += "</feed>"
        return response

    @patch.object(ArXivClient, "fetch_with_retry")
    def test_fetch_recent_pagination(self, mock_fetch):
        """Test pagination handling in fetch_recent."""
        # Create responses for pagination test
        first_page = self._create_test_response(0, 100, total=150)
        second_page = self._create_test_response(100, 50)

        # Mock to return different responses
        mock_fetch.side_effect = [first_page, second_page]

        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 2)
        )

        # Should have fetched all 150 papers
        self.assertEqual(len(papers), 150)
        self.assertEqual(
            mock_fetch.call_count, 2
        )  # Two pages (second page returns < page_size, so stops)

    def test_rate_limiter(self):
        """Test that rate limiter enforces delays between requests."""
        with patch("time.sleep") as mock_sleep:
            with patch.object(self.client, "fetch") as mock_fetch:
                mock_fetch.return_value = self.sample_xml_response

                # Make two rapid requests
                self.client.fetch_with_rate_limit("/query")
                self.client.fetch_with_rate_limit("/query")

                # Should have slept to respect rate limit
                mock_sleep.assert_called()
