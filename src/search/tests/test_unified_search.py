from unittest.mock import MagicMock, Mock

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from search.services.unified_search_query_builder import (
    DocumentQueryBuilder,
    FieldConfig,
)
from search.services.unified_search_service import UnifiedSearchService


class UnifiedSearchServiceTests(TestCase):
    def setUp(self):
        self.service = UnifiedSearchService()

    def test_build_document_query(self):
        query = self.service.query_builder.build_document_query("machine learning")
        qd = query.to_dict()
        self.assertIn("bool", qd)
        self.assertGreater(len(qd["bool"]["should"]), 0)

    def test_process_document_results_paper(self):
        mock_hit = MagicMock()
        mock_hit.id = "123"
        mock_hit.meta.index = "paper"
        mock_hit.meta.score = 10.5
        mock_hit.paper_title = "Test Paper"
        mock_hit.created_date = "2024-01-01"
        mock_hit.score = 50
        mock_hit.raw_authors = [
            {"first_name": "John", "last_name": "Doe", "full_name": "John Doe"}
        ]
        mock_hit.doi = "10.1234/test"
        mock_hit.citations = 42
        mock_hit.paper_publish_date = "2023-12-01"
        mock_hit.hubs = [{"id": 1, "name": "AI", "slug": "ai"}]
        mock_hit.meta.highlight = None

        mock_response = MagicMock()
        mock_response.hits = [mock_hit]

        results = self.service._process_document_results(mock_response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "paper")
        self.assertEqual(results[0]["title"], "Test Paper")

    def test_fuzzy_strategy_skips_content_on_long_query(self):
        builder = DocumentQueryBuilder("one two three four five")
        fields = [
            FieldConfig("abstract", boost=2.0, query_types=["fuzzy"]),
            FieldConfig("paper_title", boost=5.0, query_types=["fuzzy"]),
        ]
        builder.add_fuzzy_strategy(fields)
        query_dict = builder.build().to_dict()
        fields_in_query = query_dict["bool"]["should"][0]["multi_match"]["fields"]
        self.assertIn("paper_title^2", fields_in_query)
        self.assertNotIn("abstract", fields_in_query)


class UnifiedSearchViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/search/"

    def test_missing_query_parameter(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pagination_urls(self):
        service = UnifiedSearchService()
        request = Mock()
        request.path = "/api/search/"
        request.build_absolute_uri = lambda path: f"https://testserver{path}"

        url = service._build_page_url(request, "test query", 2, 10, "relevance")
        self.assertIn("page=2", url)
