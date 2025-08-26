"""
Tests for the arXiv adapter
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.ingestion.adapters.arxiv_adapter import ArxivAdapter
from paper.ingestion.tests.fixtures.arxiv_responses import (
    ARXIV_API_RESPONSE,
    ARXIV_EMPTY_RESPONSE,
    ARXIV_OAI_ERROR_RESPONSE,
    ARXIV_OAI_RESPONSE,
)


class TestArxivAdapter(TestCase):
    """Test the arXiv adapter"""

    def setUp(self):
        self.adapter = ArxivAdapter()

    def test_initialization(self):
        """Test adapter initialization"""
        self.assertEqual(self.adapter.SOURCE_NAME, "arxiv")
        self.assertEqual(self.adapter.DEFAULT_RATE_LIMIT, "1/3s")
        self.assertIsNotNone(self.adapter.categories)

    def test_initialization_with_custom_categories(self):
        """Test initialization with custom categories"""
        categories = ["cs.AI", "cs.LG"]
        adapter = ArxivAdapter(categories=categories)
        self.assertEqual(adapter.categories, categories)

    @patch.object(ArxivAdapter, "_make_request")
    def test_fetch_recent(self, mock_request):
        """Test fetching recent papers"""
        mock_response = MagicMock()
        mock_response.text = ARXIV_API_RESPONSE
        mock_request.return_value = mock_response

        results = list(self.adapter.fetch_recent(hours=24))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "arxiv_api")
        self.assertIn("query", results[0])
        self.assertEqual(results[0]["count"], 2)

    @patch.object(ArxivAdapter, "_make_request")
    def test_fetch_date_range_oai(self, mock_request):
        """Test fetching papers using OAI-PMH"""
        mock_response = MagicMock()
        mock_response.text = ARXIV_OAI_RESPONSE
        mock_request.return_value = mock_response

        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)

        results = list(self.adapter.fetch_date_range(start_date, end_date))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "arxiv_oai")
        self.assertEqual(results[0]["count"], 2)
        mock_request.assert_called_once()

    @patch.object(ArxivAdapter, "_make_request")
    def test_fetch_with_resumption_token(self, mock_request):
        """Test handling of OAI-PMH resumption tokens"""
        # First response with resumption token
        first_response = MagicMock()
        first_response.text = ARXIV_OAI_RESPONSE

        # Second response without resumption token (empty)
        second_response = MagicMock()
        second_response.text = ARXIV_OAI_RESPONSE.replace(
            '<resumptionToken cursor="0" completeListSize="150">2024-01-02|1001</resumptionToken>',
            "",
        )

        mock_request.side_effect = [first_response, second_response]

        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)

        results = list(self.adapter.fetch_date_range(start_date, end_date))

        self.assertEqual(len(results), 2)
        self.assertEqual(mock_request.call_count, 2)

    def test_parse_api_response(self):
        """Test parsing arXiv API response"""
        response_data = {"source": "arxiv_api", "response": ARXIV_API_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        self.assertEqual(len(papers), 2)

        # Check first paper
        paper1 = papers[0]
        self.assertEqual(
            paper1["title"], "Deep Learning for Natural Language Processing: A Survey"
        )
        self.assertEqual(paper1["arxiv_id"], "2401.00001")
        self.assertEqual(paper1["version"], "1")
        self.assertEqual(len(paper1["authors"]), 2)
        self.assertEqual(paper1["authors"][0]["name"], "Jane Smith")
        self.assertIn(
            "Stanford University", paper1["authors"][0].get("affiliation", "")
        )
        self.assertEqual(paper1["doi"], "10.1234/arxiv.2401.00001")
        self.assertIn("cs.CL", paper1["categories"])
        self.assertIn("45 pages", paper1["comment"])

        # Check second paper
        paper2 = papers[1]
        self.assertEqual(
            paper2["title"],
            "Reinforcement Learning in Robotics: Current State and Future Directions",
        )
        self.assertEqual(paper2["arxiv_id"], "2401.00002")
        self.assertEqual(paper2["version"], "2")
        self.assertEqual(len(paper2["authors"]), 3)

    def test_parse_oai_response(self):
        """Test parsing OAI-PMH response"""
        response_data = {"source": "arxiv_oai", "response": ARXIV_OAI_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        self.assertEqual(len(papers), 2)

        # Check first paper
        paper1 = papers[0]
        self.assertEqual(
            paper1["title"],
            "Quantum Computing for Machine Learning: A Comprehensive Review",
        )
        self.assertEqual(paper1["arxiv_id"], "2401.00003")
        self.assertEqual(len(paper1["authors"]), 2)
        self.assertEqual(paper1["authors"][0]["family"], "Smith")
        self.assertEqual(paper1["authors"][0]["given"], "Jane A.")
        self.assertEqual(paper1["doi"], "10.1038/s41586-024-00001")
        self.assertIn("cs.LG", paper1["categories"])

        # Check second paper
        paper2 = papers[1]
        self.assertEqual(paper2["title"], "New Results in Algebraic Topology")
        self.assertEqual(paper2["arxiv_id"], "2401.00004")

    def test_parse_empty_response(self):
        """Test parsing empty response"""
        response_data = {"source": "arxiv_api", "response": ARXIV_EMPTY_RESPONSE}

        papers = self.adapter.parse_response(response_data)
        self.assertEqual(len(papers), 0)

    def test_parse_oai_error_response(self):
        """Test handling OAI-PMH error response"""
        response_data = {"source": "arxiv_oai", "response": ARXIV_OAI_ERROR_RESPONSE}

        papers = self.adapter.parse_response(response_data)
        self.assertEqual(len(papers), 0)

    @patch.object(ArxivAdapter, "_make_request")
    def test_fetch_by_id(self, mock_request):
        """Test fetching a paper by arXiv ID"""
        mock_response = MagicMock()
        mock_response.text = ARXIV_API_RESPONSE
        mock_request.return_value = mock_response

        result = self.adapter.fetch_by_id("2401.00001")

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "arxiv_api")
        self.assertEqual(result["query"], "id:2401.00001")
        mock_request.assert_called_once()

    def test_pdf_url_generation(self):
        """Test that PDF URLs are correctly generated"""
        response_data = {"source": "arxiv_api", "response": ARXIV_API_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        # Check PDF URLs
        self.assertEqual(papers[0]["pdf_url"], "https://arxiv.org/pdf/2401.00001.pdf")
        self.assertEqual(papers[1]["pdf_url"], "https://arxiv.org/pdf/2401.00002.pdf")

    def test_categories_extraction(self):
        """Test that categories are properly extracted"""
        response_data = {"source": "arxiv_api", "response": ARXIV_API_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        # First paper should have cs.CL as primary category
        self.assertEqual(papers[0]["primary_category"], "cs.CL")
        self.assertIn("cs.AI", papers[0]["categories"])
        self.assertIn("cs.LG", papers[0]["categories"])

        # Second paper should have cs.RO as primary
        self.assertEqual(papers[1]["primary_category"], "cs.RO")
