"""
Tests for ArXiv OAI client.
"""

import os
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

from paper.ingestion.clients.preprints.arxiv_oai import (
    ArXivOAIClient,
    ArXivOAIConfig,
    parse_xml_metadata,
)


class TestArXivOAIClient(TestCase):

    def setUp(self):
        self.config = ArXivOAIConfig()
        self.client = ArXivOAIClient(self.config)

        # Load fixture files
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")

        with open(
            os.path.join(fixtures_dir, "arxiv_oai_sample_response.xml"), "r"
        ) as f:
            self.sample_xml_response = f.read()

        with open(os.path.join(fixtures_dir, "arxiv_oai_empty_response.xml"), "r") as f:
            self.empty_xml_response = f.read()

        with open(
            os.path.join(fixtures_dir, "arxiv_oai_with_resumption.xml"), "r"
        ) as f:
            self.resumption_xml_response = f.read()

        with open(
            os.path.join(fixtures_dir, "arxiv_oai_metadata_sample.xml"), "r"
        ) as f:
            self.sample_metadata_xml = f.read()

    def test_config_defaults(self):
        """
        Test ArXiv OAI config has correct defaults.
        """
        # Act
        config = ArXivOAIConfig()

        # Assert
        self.assertEqual(config.source_name, "arxiv_oai")
        self.assertEqual(config.base_url, "https://oaipmh.arxiv.org/oai")
        self.assertEqual(config.rate_limit, 0.33)  # 3 second delay
        self.assertEqual(config.request_timeout, 60.0)
        self.assertEqual(config.metadata_prefix, "arXiv")

    def test_parse(self):
        """
        Test parsing of ArXiv OAI XML response.
        """
        # Act
        papers = self.client.parse(self.sample_xml_response)

        # Assert
        self.assertEqual(len(papers), 2)

        # Check that papers contain parsed data
        paper1 = papers[0]
        self.assertEqual(paper1["source"], "arxiv_oai")
        self.assertEqual(paper1["id"], "2501.08827")
        self.assertEqual(
            paper1["title"],
            "A Survey of Reinforcement Learning for Large Reasoning Models",
        )
        self.assertEqual(paper1["authors"][0]["keyname"], "Zhang")
        self.assertEqual(paper1["authors"][0]["forenames"], "Kaiyan")

        # Check second paper
        paper2 = papers[1]
        self.assertEqual(paper2["source"], "arxiv_oai")
        self.assertEqual(paper2["id"], "2501.08817")
        self.assertIn("Quantum Cardinality", paper2["title"])

    def test_parse_empty_response(self):
        """
        Test parsing empty XML response.
        """
        # Act
        papers = self.client.parse(self.empty_xml_response)

        # Assert
        self.assertEqual(papers, [])

    def test_parse_invalid_xml(self):
        """
        Test parsing invalid XML returns empty list.
        """
        # Act
        papers = self.client.parse("Invalid XML content")

        # Assert
        self.assertEqual(papers, [])

    def test_parse_xml_metadata(self):
        """
        Test XML metadata parsing function.
        """
        # Act
        parsed = parse_xml_metadata(self.sample_metadata_xml)

        # Assert
        # Check basic fields
        self.assertEqual(parsed["id"], "2507.00004")
        self.assertEqual(
            parsed["title"],
            "A Theory of Inference Compute Scaling: Reasoning through "
            "Directed Stochastic Skill Search",
        )
        self.assertIn("Large language models", parsed["abstract"])
        self.assertEqual(parsed["created"], "2025-07-10")
        self.assertEqual(parsed["updated"], "2025-07-11")

        # Check authors
        self.assertEqual(len(parsed["authors"]), 3)
        self.assertEqual(parsed["authors"][0]["name"], "Austin R. Ellis-Mohr")
        self.assertEqual(parsed["authors"][0]["keyname"], "Ellis-Mohr")
        self.assertEqual(parsed["authors"][0]["forenames"], "Austin R.")
        self.assertEqual(parsed["authors"][2]["name"], "Lav R. Varshney")

        # Check categories
        self.assertEqual(parsed["categories"], ["cs.LG", "cs.AI", "cs.CY", "cs.PF"])
        self.assertEqual(parsed["primary_category"], "cs.LG")

        # Check links
        self.assertEqual(
            parsed["links"]["alternate"],
            "https://arxiv.org/abs/2507.00004",
        )
        self.assertEqual(
            parsed["links"]["pdf"],
            "https://arxiv.org/pdf/2507.00004.pdf",
        )

    def test_extract_resumption_token(self):
        """
        Test extracting resumption token from response.
        """
        # Act
        token = self.client._extract_resumption_token(self.resumption_xml_response)

        # Assert
        self.assertEqual(token, "token123abc")

    def test_extract_resumption_token_none(self):
        """
        Test extracting resumption token when none exists.
        """
        # Act
        token = self.client._extract_resumption_token(self.sample_xml_response)

        # Assert
        self.assertIsNone(token)

    @patch("requests.Session.get")
    def test_fetch_with_retry(self, mock_get):
        """
        Test fetch with retry logic.
        """
        # Arrange
        mock_response = MagicMock()
        mock_response.text = self.sample_xml_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Act
        result = self.client.fetch_with_retry(
            "", {"verb": "ListRecords", "metadataPrefix": "arXiv"}
        )

        # Assert
        self.assertEqual(result, self.sample_xml_response)
        mock_get.assert_called_once()

    @patch.object(ArXivOAIClient, "fetch_with_retry")
    def test_fetch_recent(self, mock_fetch):
        """
        Test fetching recent papers.
        """
        # Arrange
        mock_fetch.side_effect = [
            self.sample_xml_response,
        ]

        # Act
        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1),
            until=datetime(2025, 1, 7),
        )

        # Assert - Check results
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0]["id"], "2501.08827")

        # Verify query was constructed correctly
        first_call_args = mock_fetch.call_args_list[0]
        params = first_call_args[0][1]  # Get params from first call
        self.assertEqual(params["verb"], "ListRecords")
        self.assertEqual(params["metadataPrefix"], "arXiv")
        self.assertEqual(params["from"], "2025-01-01")
        self.assertEqual(params["until"], "2025-01-07")

    @patch.object(ArXivOAIClient, "fetch_with_retry")
    def test_fetch_recent_with_resumption_token(self, mock_fetch):
        """
        Test pagination with resumption token.
        """
        # Arrange
        mock_fetch.side_effect = [
            self.resumption_xml_response,
            self.sample_xml_response,
        ]

        # Act
        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 7)
        )

        # Assert - Should have made two requests
        self.assertEqual(mock_fetch.call_count, 2)

        # Second request should use resumption token
        second_call_params = mock_fetch.call_args_list[1][0][1]
        self.assertEqual(second_call_params["verb"], "ListRecords")
        self.assertEqual(second_call_params["resumptionToken"], "token123abc")
        # Other params should not be present when using resumption token
        self.assertNotIn("from", second_call_params)
        self.assertNotIn("until", second_call_params)
        self.assertNotIn("metadataPrefix", second_call_params)

        # Should have fetched papers from both responses
        self.assertEqual(len(papers), 3)
