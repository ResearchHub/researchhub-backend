from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from paper.models import Paper
from paper.tests.helpers import create_paper
from utils.doi import DOI


class SuggestViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("suggest")

    def test_missing_query_param(self):
        """Test that missing query parameter returns 400"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Search query is required")

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_empty_results(self, mock_es_execute, mock_openalex):
        """Test handling of empty results from both sources"""
        # Mock OpenAlex response
        mock_openalex.return_value = {"results": []}

        # Mock Elasticsearch response
        class MockSuggest:
            def to_dict(self):
                return {"suggestions": []}

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        response = self.client.get(self.url + "?q=test")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_deduplication_prefers_researchhub(self, mock_es_execute, mock_openalex):
        """Test that when same DOI exists in both sources, ResearchHub version is preferred"""
        test_doi = "10.1234/test.123"
        normalized_doi = DOI.normalize_doi(test_doi)

        # Create paper in database
        paper = create_paper()
        paper.doi = test_doi
        paper.paper_title = "Test Paper RH"
        paper.save()

        # Mock OpenAlex response
        mock_openalex.return_value = {
            "results": [
                {
                    "external_id": test_doi,
                    "display_name": "Test Paper OA",
                    "hint": "Author1, Author2",
                    "cited_by_count": 10,
                    "id": "W123",
                }
            ]
        }

        # Mock Elasticsearch response
        class MockSuggest:
            def to_dict(self):
                return {
                    "suggestions": [
                        {
                            "options": [
                                {
                                    "_score": 1.0,
                                    "_source": {
                                        "id": paper.id,
                                        "doi": test_doi,
                                        "paper_title": "Test Paper RH",
                                        "raw_authors": [{"full_name": "RH Author"}],
                                        "citations": 5,
                                    },
                                }
                            ]
                        }
                    ]
                }

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        response = self.client.get(self.url + "?q=test")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)  # Only one result due to deduplication
        self.assertEqual(
            response.data[0]["source"], "researchhub"
        )  # RH version preferred
        self.assertEqual(response.data[0]["display_name"], "Test Paper RH")

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_combines_unique_results(self, mock_es_execute, mock_openalex):
        """Test that results with different DOIs from both sources are combined"""
        # Mock OpenAlex response
        mock_openalex.return_value = {
            "results": [
                {
                    "external_id": "10.1234/oa.123",
                    "display_name": "OpenAlex Paper",
                    "hint": "Author1, Author2",
                    "cited_by_count": 10,
                    "id": "W123",
                }
            ]
        }

        # Mock Elasticsearch response
        class MockSuggest:
            def to_dict(self):
                return {
                    "suggestions": [
                        {
                            "options": [
                                {
                                    "_score": 1.0,
                                    "_source": {
                                        "id": 1,
                                        "doi": "10.1234/rh.123",
                                        "paper_title": "ResearchHub Paper",
                                        "raw_authors": [{"full_name": "RH Author"}],
                                        "citations": 5,
                                    },
                                }
                            ]
                        }
                    ]
                }

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        response = self.client.get(self.url + "?q=test")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)  # Both results included

        # Verify both sources are represented
        sources = {result["source"] for result in response.data}
        self.assertEqual(sources, {"researchhub", "openalex"})

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_handles_missing_fields_gracefully(self, mock_es_execute, mock_openalex):
        """Test that missing optional fields don't cause errors"""
        # Mock OpenAlex response with missing fields
        mock_openalex.return_value = {
            "results": [
                {
                    "external_id": "10.1234/oa.123",
                    "display_name": "OpenAlex Paper",
                    # Missing hint and cited_by_count
                    "id": "W123",
                }
            ]
        }

        # Mock Elasticsearch response with missing fields
        class MockSuggest:
            def to_dict(self):
                return {
                    "suggestions": [
                        {
                            "options": [
                                {
                                    "_source": {
                                        "doi": "10.1234/rh.123",
                                        # Missing other fields
                                    },
                                }
                            ]
                        }
                    ]
                }

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        response = self.client.get(self.url + "?q=test")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify results have default values for missing fields
        for result in response.data:
            self.assertIn("display_name", result)
            self.assertIn("authors", result)
            self.assertIn("_score", result)
            self.assertIn("citations", result)

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_error_handling(self, mock_es_execute, mock_openalex):
        """Test handling of errors from both sources"""
        # Mock OpenAlex error
        mock_openalex.side_effect = Exception("OpenAlex API error")

        # Mock Elasticsearch error
        mock_es_execute.side_effect = Exception("Elasticsearch error")

        response = self.client.get(self.url + "?q=test")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("error", response.data)
