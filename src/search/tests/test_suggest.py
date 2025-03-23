from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from paper.tests.helpers import create_paper


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
        """Test that when same DOI exists in both sources, RH version is preferred"""
        test_doi = "10.1234/test.123"

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
                    "publication_date": "2023-01-01",
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
                                        "created_date": "2023-01-01",
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
                    "publication_date": "2023-01-01",
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
                                        "created_date": "2023-01-01",
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
            self.assertIn("citations", result)
            self.assertIn("created_date", result)

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

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_invalid_index_parameter(self, mock_es_execute, mock_openalex):
        """Test handling of invalid index parameter"""
        response = self.client.get(self.url + "?q=test&index=invalid_index")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid indexes: invalid_index", response.data["error"])
        self.assertIn(
            "Available indexes:", response.data["error"]
        )  # Should list available indexes

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_multiple_indexes(self, mock_es_execute, mock_openalex):
        """Test searching across multiple indexes"""
        # Mock OpenAlex response
        mock_openalex.return_value = {"results": []}

        # Mock Elasticsearch response for paper index
        paper_options = [
            {
                "_score": 1.0,
                "_source": {
                    "id": 1,
                    "doi": "10.1234/paper.123",
                    "paper_title": "Test Paper",
                    "raw_authors": [{"full_name": "Author 1"}],
                    "citations": 10,
                    "created_date": "2023-01-01",
                },
            }
        ]

        # Mock Elasticsearch response for user index
        user_options = [
            {
                "_score": 1.0,
                "_source": {
                    "id": 2,
                    "full_name": "Test User",
                    "created_date": "2023-02-01",
                },
            }
        ]

        # Setup mock response
        def mock_execute_side_effect():
            class MockSuggest:
                def to_dict(self):
                    if "paper" in mock_es_execute.call_args[0][0].index:
                        return {"suggestions": [{"options": paper_options}]}
                    elif "user" in mock_es_execute.call_args[0][0].index:
                        return {"suggestions": [{"options": user_options}]}
                    return {"suggestions": []}

            class MockResponse:
                suggest = MockSuggest()

            return MockResponse()

        mock_es_execute.side_effect = mock_execute_side_effect

        response = self.client.get(self.url + "?q=test&index=paper,user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should have results from both indexes
        entity_types = [result["entity_type"] for result in response.data]
        self.assertIn("paper", entity_types)
        self.assertIn("user", entity_types)

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_empty_query_sanitization(self, mock_es_execute, mock_openalex):
        """Test that empty spaces in query are handled properly"""
        # Try with just spaces
        response = self.client.get(self.url + "?q=   ")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Search query is required")

        # Try with empty string
        response = self.client.get(self.url + "?q=")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Search query is required")

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_limit_parameter(self, mock_es_execute, mock_openalex):
        """Test that limit parameter restricts the number of results"""
        # Create numerous results
        openalex_results = []

        # Generate 15 test results
        for i in range(15):
            openalex_results.append(
                {
                    "external_id": f"10.1234/test.{i}",
                    "display_name": f"Test Paper {i}",
                    "hint": f"Author {i}",
                    "cited_by_count": i,
                    "id": f"W{i}",
                    "publication_date": "2023-01-01",
                }
            )

        # Mock OpenAlex response with many results
        mock_openalex.return_value = {"results": openalex_results}

        # Mock empty Elasticsearch response
        class MockSuggest:
            def to_dict(self):
                return {"suggestions": []}

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        # Test with default limit (10)
        response = self.client.get(self.url + "?q=test")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)  # Should be limited to 10 results

        # Test with custom limit
        response = self.client.get(self.url + "?q=test&limit=5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)  # Should be limited to 5 results

        # Test with limit higher than available results
        response = self.client.get(self.url + "?q=test&limit=20")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 15)  # Should return all 15 available

        # Test with invalid limit
        response = self.client.get(self.url + "?q=test&limit=invalid")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)  # Should use default of 10
