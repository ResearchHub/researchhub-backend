"""
Tests for the PubMed adapter
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.ingestion.adapters.pubmed_adapter import PubmedAdapter
from paper.ingestion.tests.fixtures.pubmed_responses import (
    PUBMED_EFETCH_RESPONSE,
    PUBMED_EMPTY_SEARCH,
    PUBMED_ESEARCH_RESPONSE,
    PUBMED_PMC_RESPONSE,
)


class TestPubmedAdapter(TestCase):
    """Test the PubMed adapter"""

    def setUp(self):
        self.adapter = PubmedAdapter()
        self.adapter_with_key = PubmedAdapter(api_key="test_api_key_123")

    def test_initialization(self):
        """Test adapter initialization"""
        self.assertEqual(self.adapter.SOURCE_NAME, "pubmed")
        self.assertEqual(self.adapter.DEFAULT_RATE_LIMIT, "3/s")
        self.assertIsNone(self.adapter.api_key)

    def test_initialization_with_api_key(self):
        """Test initialization with API key adjusts rate limit"""
        self.assertEqual(self.adapter_with_key.api_key, "test_api_key_123")
        self.assertEqual(self.adapter_with_key.rate_limit, "10/s")

    def test_get_auth_headers(self):
        """Test API key is added to headers"""
        headers = self.adapter._get_auth_headers()
        self.assertEqual(headers, {})

        headers = self.adapter_with_key._get_auth_headers()
        self.assertEqual(headers, {"api_key": "test_api_key_123"})

    @patch.object(PubmedAdapter, "_make_request")
    def test_fetch_recent(self, mock_request):
        """Test fetching recent papers"""
        # Mock ESearch response
        search_response = MagicMock()
        search_response.json.return_value = PUBMED_ESEARCH_RESPONSE

        # Mock EFetch response
        fetch_response = MagicMock()
        fetch_response.text = PUBMED_EFETCH_RESPONSE

        mock_request.side_effect = [search_response, fetch_response]

        results = list(self.adapter.fetch_recent(hours=24))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "pubmed_efetch")
        self.assertEqual(results[0]["total_count"], 3)
        self.assertEqual(results[0]["batch_size"], 3)
        self.assertIn("query_label", results[0])

    @patch.object(PubmedAdapter, "_make_request")
    def test_fetch_date_range(self, mock_request):
        """Test fetching papers in a date range"""
        search_response = MagicMock()
        search_response.json.return_value = PUBMED_ESEARCH_RESPONSE

        fetch_response = MagicMock()
        fetch_response.text = PUBMED_EFETCH_RESPONSE

        mock_request.side_effect = [search_response, fetch_response]

        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 15)

        results = list(self.adapter.fetch_date_range(start_date, end_date))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["query_label"], "2024/01/01_2024/01/15")

    @patch.object(PubmedAdapter, "_make_request")
    def test_empty_search_results(self, mock_request):
        """Test handling of empty search results"""
        search_response = MagicMock()
        search_response.json.return_value = PUBMED_EMPTY_SEARCH

        mock_request.return_value = search_response

        results = list(self.adapter.fetch_recent(hours=24))

        self.assertEqual(len(results), 0)
        # Only ESearch should be called, not EFetch
        self.assertEqual(mock_request.call_count, 1)

    @patch.object(PubmedAdapter, "_make_request")
    def test_batch_fetching(self, mock_request):
        """Test batch fetching with multiple pages"""
        # Mock search with 250 results
        large_search = PUBMED_ESEARCH_RESPONSE.copy()
        large_search["esearchresult"]["count"] = "250"

        search_response = MagicMock()
        search_response.json.return_value = large_search

        # Mock two fetch responses (batch_size=200)
        fetch1 = MagicMock()
        fetch1.text = PUBMED_EFETCH_RESPONSE

        fetch2 = MagicMock()
        fetch2.text = PUBMED_EFETCH_RESPONSE

        mock_request.side_effect = [search_response, fetch1, fetch2]

        results = list(self.adapter.fetch_recent(hours=24))

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["batch_start"], 0)
        self.assertEqual(results[0]["batch_size"], 200)
        self.assertEqual(results[1]["batch_start"], 200)
        self.assertEqual(results[1]["batch_size"], 50)

    def test_parse_response(self):
        """Test parsing PubMed XML response"""
        response_data = {"source": "pubmed_efetch", "response": PUBMED_EFETCH_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        self.assertEqual(len(papers), 2)

        # Check first paper (complete record)
        paper1 = papers[0]
        self.assertEqual(
            paper1["title"],
            "Novel therapeutic approach for Alzheimer's disease using targeted gene therapy",
        )
        self.assertEqual(paper1["pmid"], 38234567)
        self.assertEqual(paper1["doi"], "10.1038/s41591-024-01234")
        self.assertEqual(len(paper1["authors"]), 3)
        self.assertEqual(paper1["authors"][0]["family"], "Johnson")
        self.assertEqual(paper1["authors"][0]["given"], "Emily R")
        self.assertIn("Harvard Medical School", paper1["authors"][0]["affiliation"])
        self.assertEqual(paper1["authors"][0]["orcid"], "0000-0001-2345-6789")
        self.assertTrue(paper1["is_preprint"])
        self.assertIn("Alzheimer Disease", paper1["metadata"]["mesh_terms"])

        # Check second paper (minimal record)
        paper2 = papers[1]
        self.assertEqual(
            paper2["title"],
            "Structural basis of SARS-CoV-2 variant immune escape mechanisms",
        )
        self.assertEqual(paper2["pmid"], 38234568)
        self.assertEqual(paper2["doi"], "10.1016/j.cell.2024.01.001")
        self.assertEqual(len(paper2["authors"]), 2)

    def test_parse_pmc_response(self):
        """Test parsing paper with PMC ID"""
        response_data = {"source": "pubmed_efetch", "response": PUBMED_PMC_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        self.assertEqual(len(papers), 1)

        paper = papers[0]
        self.assertEqual(paper["pmid"], 38234569)
        self.assertEqual(paper["pmcid"], "PMC10987655")
        self.assertEqual(
            paper["pdf_url"],
            "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10987655/pdf/",
        )

    @patch.object(PubmedAdapter, "_make_request")
    def test_fetch_by_pmid(self, mock_request):
        """Test fetching a single paper by PMID"""
        mock_response = MagicMock()
        mock_response.text = PUBMED_EFETCH_RESPONSE
        mock_request.return_value = mock_response

        result = self.adapter.fetch_by_pmid("38234567")

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "pubmed_efetch")
        self.assertEqual(result["pmid"], "38234567")
        self.assertEqual(result["count"], 1)

        # Check API key is included if present
        if self.adapter.api_key:
            call_args = mock_request.call_args
            self.assertIn("api_key", call_args[1]["params"])

    @patch.object(PubmedAdapter, "_make_request")
    def test_search_method(self, mock_request):
        """Test the search method returns PMIDs"""
        mock_response = MagicMock()
        mock_response.json.return_value = PUBMED_ESEARCH_RESPONSE
        mock_request.return_value = mock_response

        pmids = self.adapter.search("Alzheimer disease", max_results=10)

        self.assertEqual(len(pmids), 3)
        self.assertIn("38234567", pmids)
        self.assertIn("38234568", pmids)
        self.assertIn("38234569", pmids)

    def test_abstract_parsing(self):
        """Test that structured abstracts are parsed correctly"""
        response_data = {"source": "pubmed_efetch", "response": PUBMED_EFETCH_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        # First paper has structured abstract with labels
        abstract = papers[0]["abstract"]
        self.assertIn("BACKGROUND:", abstract)
        self.assertIn("METHODS:", abstract)
        self.assertIn("RESULTS:", abstract)
        self.assertIn("CONCLUSIONS:", abstract)

    def test_publication_type_detection(self):
        """Test detection of preprints vs published papers"""
        response_data = {"source": "pubmed_efetch", "response": PUBMED_EFETCH_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        # First paper is marked as preprint
        self.assertTrue(papers[0]["is_preprint"])
        self.assertIn("Preprint", papers[0]["metadata"]["publication_types"])

        # Second paper is not a preprint
        self.assertFalse(papers[1]["is_preprint"])

    def test_url_generation(self):
        """Test that PubMed URLs are correctly generated"""
        response_data = {"source": "pubmed_efetch", "response": PUBMED_EFETCH_RESPONSE}

        papers = self.adapter.parse_response(response_data)

        self.assertEqual(papers[0]["url"], "https://pubmed.ncbi.nlm.nih.gov/38234567/")
        self.assertEqual(papers[1]["url"], "https://pubmed.ncbi.nlm.nih.gov/38234568/")
