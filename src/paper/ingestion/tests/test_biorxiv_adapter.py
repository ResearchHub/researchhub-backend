"""
Tests for the bioRxiv/medRxiv adapter
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.ingestion.adapters.biorxiv_adapter import BiorxivMedrxivAdapter
from paper.ingestion.tests.fixtures.biorxiv_responses import (
    BIORXIV_API_RESPONSE,
    BIORXIV_EMPTY_RESPONSE,
    BIORXIV_PUBS_RESPONSE,
    MEDRXIV_API_RESPONSE,
)


class TestBiorxivMedrxivAdapter(TestCase):
    """Test the bioRxiv/medRxiv adapter"""

    def setUp(self):
        self.biorxiv_adapter = BiorxivMedrxivAdapter(server="biorxiv")
        self.medrxiv_adapter = BiorxivMedrxivAdapter(server="medrxiv")

    def test_initialization(self):
        """Test adapter initialization"""
        self.assertEqual(self.biorxiv_adapter.SOURCE_NAME, "biorxiv")
        self.assertEqual(self.biorxiv_adapter.server, "biorxiv")
        self.assertEqual(self.medrxiv_adapter.SOURCE_NAME, "medrxiv")
        self.assertEqual(self.medrxiv_adapter.server, "medrxiv")

    def test_invalid_server(self):
        """Test initialization with invalid server"""
        with self.assertRaises(ValueError) as context:
            BiorxivMedrxivAdapter(server="invalid")
        self.assertIn("Invalid server", str(context.exception))

    @patch.object(BiorxivMedrxivAdapter, "_make_request")
    def test_fetch_recent_biorxiv(self, mock_request):
        """Test fetching recent bioRxiv papers"""
        mock_response = MagicMock()
        mock_response.json.return_value = BIORXIV_API_RESPONSE
        mock_request.return_value = mock_response

        results = list(self.biorxiv_adapter.fetch_recent(hours=24))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "biorxiv_api")
        self.assertEqual(results[0]["interval"], "1d")
        self.assertEqual(results[0]["count"], 2)

    @patch.object(BiorxivMedrxivAdapter, "_make_request")
    def test_fetch_recent_medrxiv(self, mock_request):
        """Test fetching recent medRxiv papers"""
        mock_response = MagicMock()
        mock_response.json.return_value = MEDRXIV_API_RESPONSE
        mock_request.return_value = mock_response

        results = list(self.medrxiv_adapter.fetch_recent(hours=48))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "medrxiv_api")
        self.assertEqual(results[0]["interval"], "2d")

    @patch.object(BiorxivMedrxivAdapter, "_make_request")
    def test_fetch_date_range(self, mock_request):
        """Test fetching papers in a date range"""
        mock_response = MagicMock()
        mock_response.json.return_value = BIORXIV_API_RESPONSE
        mock_request.return_value = mock_response

        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)

        results = list(self.biorxiv_adapter.fetch_date_range(start_date, end_date))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["from_date"], "2024-01-01")
        self.assertEqual(results[0]["to_date"], "2024-01-02")
        self.assertEqual(results[0]["cursor"], 0)

    @patch.object(BiorxivMedrxivAdapter, "_make_request")
    def test_pagination(self, mock_request):
        """Test pagination with cursor"""
        # First response with 100 papers (simulated by collection size)
        first_response = MagicMock()
        first_data = BIORXIV_API_RESPONSE.copy()
        # Add 98 more dummy papers to simulate full page
        first_data["collection"].extend([first_data["collection"][0]] * 98)
        first_response.json.return_value = first_data

        # Second response with fewer papers
        second_response = MagicMock()
        second_response.json.return_value = BIORXIV_API_RESPONSE

        mock_request.side_effect = [first_response, second_response]

        results = list(self.biorxiv_adapter.fetch_recent(hours=24))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["cursor"], 0)
        self.assertEqual(results[1]["cursor"], 100)

    def test_parse_biorxiv_response(self):
        """Test parsing bioRxiv API response"""
        response_data = {
            "source": "biorxiv_api",
            "response": json.dumps(BIORXIV_API_RESPONSE),
        }

        papers = self.biorxiv_adapter.parse_response(response_data)

        self.assertEqual(len(papers), 2)

        # Check first paper
        paper1 = papers[0]
        self.assertEqual(
            paper1["title"],
            "Single-cell RNA sequencing reveals novel cell types in mouse brain",
        )
        self.assertEqual(paper1["doi"], "10.1101/2024.01.01.123456")
        self.assertEqual(paper1["version"], "1")
        self.assertEqual(paper1["category"], "neuroscience")
        self.assertEqual(paper1["server"], "biorxiv")
        self.assertEqual(len(paper1["authors"]), 3)
        self.assertEqual(paper1["authors"][0]["family"], "Smith")
        self.assertEqual(paper1["authors"][0]["given"], "Jane A.")
        self.assertIn(
            "Harvard Medical School",
            paper1["metadata"]["author_corresponding_institution"],
        )

        # Check second paper (with published DOI)
        paper2 = papers[1]
        self.assertEqual(paper2["doi"], "10.1101/2024.01.01.234567")
        self.assertEqual(paper2["version"], "2")
        self.assertEqual(
            paper2["metadata"]["published_doi"], "10.1038/s41586-024-12345"
        )

    def test_parse_medrxiv_response(self):
        """Test parsing medRxiv API response"""
        response_data = {
            "source": "medrxiv_api",
            "response": json.dumps(MEDRXIV_API_RESPONSE),
        }

        papers = self.medrxiv_adapter.parse_response(response_data)

        self.assertEqual(len(papers), 2)

        # Check first paper
        paper1 = papers[0]
        self.assertEqual(
            paper1["title"],
            "Effectiveness of COVID-19 vaccines against Omicron variant: A systematic review and meta-analysis",
        )
        self.assertEqual(paper1["category"], "epidemiology")
        self.assertEqual(paper1["server"], "medrxiv")
        self.assertIn(
            "Johns Hopkins", paper1["metadata"]["author_corresponding_institution"]
        )

    def test_parse_empty_response(self):
        """Test parsing empty response"""
        response_data = {
            "source": "biorxiv_api",
            "response": json.dumps(BIORXIV_EMPTY_RESPONSE),
        }

        papers = self.biorxiv_adapter.parse_response(response_data)
        self.assertEqual(len(papers), 0)

    @patch.object(BiorxivMedrxivAdapter, "_make_request")
    def test_fetch_by_doi(self, mock_request):
        """Test fetching a paper by DOI"""
        mock_response = MagicMock()
        mock_response.json.return_value = BIORXIV_API_RESPONSE
        mock_request.return_value = mock_response

        result = self.biorxiv_adapter.fetch_by_doi("10.1101/2024.01.01.123456")

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "biorxiv_api")
        self.assertEqual(result["doi"], "10.1101/2024.01.01.123456")
        mock_request.assert_called_once()

    @patch.object(BiorxivMedrxivAdapter, "_make_request")
    def test_fetch_by_doi_with_prefix(self, mock_request):
        """Test that DOI prefix is stripped correctly"""
        mock_response = MagicMock()
        mock_response.json.return_value = BIORXIV_API_RESPONSE
        mock_request.return_value = mock_response

        result = self.biorxiv_adapter.fetch_by_doi("10.1101/2024.01.01.123456")

        # Check that the URL was constructed correctly
        expected_url = (
            "https://api.biorxiv.org/details/biorxiv/2024.01.01.123456/na/json"
        )
        mock_request.assert_called_with(expected_url)

    @patch.object(BiorxivMedrxivAdapter, "_make_request")
    def test_fetch_published_versions(self, mock_request):
        """Test fetching published versions using /pubs endpoint"""
        mock_response = MagicMock()
        mock_response.json.return_value = BIORXIV_PUBS_RESPONSE
        mock_request.return_value = mock_response

        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 2)

        results = list(
            self.biorxiv_adapter.fetch_published_versions(start_date, end_date)
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "biorxiv_pubs")

        # Parse and check the published paper
        papers = self.biorxiv_adapter.parse_response(results[0])
        self.assertEqual(len(papers), 1)
        self.assertEqual(
            papers[0]["metadata"]["published_doi"], "10.1038/nature.2024.12345"
        )

    def test_pdf_url_generation(self):
        """Test that PDF URLs are correctly generated"""
        response_data = {
            "source": "biorxiv_api",
            "response": json.dumps(BIORXIV_API_RESPONSE),
        }

        papers = self.biorxiv_adapter.parse_response(response_data)

        # Check PDF URLs
        self.assertEqual(
            papers[0]["pdf_url"],
            "https://www.biorxiv.org/content/10.1101/2024.01.01.123456v1.full.pdf",
        )
        self.assertEqual(
            papers[1]["pdf_url"],
            "https://www.biorxiv.org/content/10.1101/2024.01.01.234567v2.full.pdf",
        )

    def test_author_parsing(self):
        """Test that authors are parsed correctly"""
        response_data = {
            "source": "biorxiv_api",
            "response": json.dumps(BIORXIV_API_RESPONSE),
        }

        papers = self.biorxiv_adapter.parse_response(response_data)

        # Check authors of first paper
        authors = papers[0]["authors"]
        self.assertEqual(len(authors), 3)
        self.assertEqual(authors[0]["family"], "Smith")
        self.assertEqual(authors[0]["given"], "Jane A.")
        self.assertEqual(authors[1]["family"], "Johnson")
        self.assertEqual(authors[1]["given"], "Robert B.")
        self.assertEqual(authors[2]["family"], "Lee")
        self.assertEqual(authors[2]["given"], "Maria C.")
