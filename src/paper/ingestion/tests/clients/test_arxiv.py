"""
Tests for ArXiv client.
"""

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

        # Real ArXiv API response from Sept 2025
        self.sample_xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link href="http://arxiv.org/api/query?search_query%3Dcat%3Acs.AI%26id_list%3D%26start%3D0%26max_results%3D2" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query: search_query=cat:cs.AI&amp;id_list=&amp;start=0&amp;max_results=2</title>
  <id>http://arxiv.org/api/sLG0txIUz7g/GKW7ibPhDY0NNSQ</id>
  <updated>2025-09-11T00:00:00-04:00</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">141182</opensearch:totalResults>
  <opensearch:startIndex xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:startIndex>
  <opensearch:itemsPerPage xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/2509.08827v1</id>
    <updated>2025-09-10T17:59:43Z</updated>
    <published>2025-09-10T17:59:43Z</published>
    <title>A Survey of Reinforcement Learning for Large Reasoning Models</title>
    <summary>  In this paper, we survey recent advances in Reinforcement Learning (RL) for
reasoning with Large Language Models (LLMs). RL has achieved remarkable success
in advancing the frontier of LLM capabilities, particularly in addressing
complex logical tasks such as mathematics and coding.</summary>
    <author>
      <name>Kaiyan Zhang</name>
    </author>
    <author>
      <name>Yuxin Zuo</name>
    </author>
    <author>
      <name>Bingxiang He</name>
    </author>
    <link href="http://arxiv.org/abs/2509.08827v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2509.08827v1" rel="related" type="application/pdf"/>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2509.08817v1</id>
    <updated>2025-09-10T17:49:06Z</updated>
    <published>2025-09-10T17:49:06Z</published>
    <title>QCardEst/QCardCorr: Quantum Cardinality Estimation and Correction</title>
    <summary>  Cardinality estimation is an important part of query optimization in DBMS. We
develop a Quantum Cardinality Estimation (QCardEst) approach using Quantum
Machine Learning with a Hybrid Quantum-Classical Network.</summary>
    <author>
      <name>Tobias Winker</name>
    </author>
    <author>
      <name>Jinghua Groppe</name>
    </author>
    <author>
      <name>Sven Groppe</name>
    </author>
    <arxiv:comment xmlns:arxiv="http://arxiv.org/schemas/atom">7 pages</arxiv:comment>
    <link href="http://arxiv.org/abs/2509.08817v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2509.08817v1" rel="related" type="application/pdf"/>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="quant-ph" scheme="http://arxiv.org/schemas/atom"/>
    <category term="quant-ph" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.DB" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""

        # Empty XML response (no results)
        self.empty_xml_response = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>ArXiv Query</title>
  <id>http://arxiv.org/api/query</id>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:totalResults>
</feed>"""

    def test_config_defaults(self):
        """Test ArXiv config has correct defaults."""
        config = ArXivConfig()
        self.assertEqual(config.source_name, "arxiv")
        self.assertEqual(
            config.base_url, "http://export.arxiv.org/api"
        )  # NOSONAR - ArXiv API uses HTTP
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
        self.assertEqual(params["search_query"], "submittedDate:[20250101 TO 20250107]")

    @patch.object(ArXivClient, "fetch_with_retry")
    def test_fetch_recent_pagination(self, mock_fetch):
        """Test pagination handling in fetch_recent."""
        # Create response with 100 results
        large_response = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">150</opensearch:totalResults>"""

        # Add 100 entries
        for i in range(100):
            large_response += f"""
  <entry>
    <id>http://arxiv.org/abs/2401.{i:05d}</id>
    <title>Paper {i}</title>
    <summary>Summary {i}</summary>
    <published>2025-01-01T00:00:00Z</published>
    <updated>2025-01-01T00:00:00Z</updated>
    <author><name>Author {i}</name></author>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>"""
        large_response += "\n</feed>"

        # Second page with 50 results
        second_response = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">"""
        for i in range(100, 150):
            second_response += f"""
  <entry>
    <id>http://arxiv.org/abs/2401.{i:05d}</id>
    <title>Paper {i}</title>
    <summary>Summary {i}</summary>
    <published>2025-01-01T00:00:00Z</published>
    <updated>2025-01-01T00:00:00Z</updated>
    <author><name>Author {i}</name></author>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>"""
        second_response += "\n</feed>"

        # Mock to return different responses
        mock_fetch.side_effect = [large_response, second_response]

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
