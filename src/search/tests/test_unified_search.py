from unittest.mock import MagicMock, Mock, patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from search.services.unified_search_query_builder import (
    DEFAULT_POPULARITY_CONFIG,
    DocumentQueryBuilder,
    FieldConfig,
    PopularityConfig,
    UnifiedSearchQueryBuilder,
)
from search.services.unified_search_service import UnifiedSearchService


class UnifiedSearchServiceTests(TestCase):
    def setUp(self):
        self.service = UnifiedSearchService()

    def test_init(self):
        self.assertIsNotNone(self.service.paper_index)
        self.assertIsNotNone(self.service.post_index)

    def test_build_document_query(self):
        query = self.service.query_builder.build_document_query("machine learning")
        self.assertIsNotNone(query)
        qd = query.to_dict()
        self.assertIn("bool", qd)
        self.assertIn("should", qd["bool"])
        self.assertGreater(len(qd["bool"]["should"]), 0)

    def test_apply_sort_relevance(self):
        from opensearchpy import Search

        search = Search()
        sorted_search = self.service._apply_sort(search, "relevance")
        sort_dict = sorted_search.to_dict().get("sort", [])
        self.assertIn({"_score": {"order": "desc"}}, sort_dict)

    def test_apply_sort_newest(self):
        from opensearchpy import Search

        search = Search()
        sorted_search = self.service._apply_sort(search, "newest")
        sort_dict = sorted_search.to_dict().get("sort", [])
        self.assertTrue(any("created_date" in str(s) for s in sort_dict))

    def test_apply_sort_invalid_defaults_to_relevance(self):
        from opensearchpy import Search

        search = Search()
        sorted_search = self.service._apply_sort(search, "invalid")
        sort_dict = sorted_search.to_dict().get("sort", [])
        self.assertIn({"_score": {"order": "desc"}}, sort_dict)

    def test_apply_highlighting_documents(self):
        from opensearchpy import Search

        search = Search()
        highlighted_search = self.service._apply_highlighting(search)
        highlight_dict = highlighted_search.to_dict().get("highlight", {})
        self.assertIn("fields", highlight_dict)
        self.assertIn("paper_title", highlight_dict["fields"])
        self.assertIn("abstract", highlight_dict["fields"])
        self.assertEqual(highlight_dict["pre_tags"], ["<mark>"])
        self.assertEqual(highlight_dict["post_tags"], ["</mark>"])

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
        result = results[0]
        self.assertEqual(result["id"], "123")
        self.assertEqual(result["type"], "paper")
        self.assertEqual(result["title"], "Test Paper")
        self.assertEqual(result["doi"], "https://doi.org/10.1234/test")
        self.assertEqual(result["citations"], 42)
        self.assertEqual(len(result["hubs"]), 1)
        self.assertEqual(result["score"], 50)
        self.assertEqual(len(result["authors"]), 1)
        self.assertEqual(result["authors"][0]["first_name"], "John")
        self.assertEqual(result["authors"][0]["last_name"], "Doe")

    def test_execution_time_included_in_response(self):
        empty_doc_result = {"results": [], "count": 0}
        empty_doi_result = {"results": [], "count": 0}

        with (
            patch.object(
                self.service, "_search_documents", return_value=empty_doc_result
            ),
            patch.object(
                self.service, "_search_documents_by_doi", return_value=empty_doi_result
            ),
        ):
            mock_request = Mock()
            mock_request.path = "/api/search/"
            mock_request.build_absolute_uri = lambda path: f"https://testserver{path}"

            results = self.service.search(
                query="test query",
                page=1,
                page_size=10,
                sort="relevance",
                request=mock_request,
            )

            self.assertIn("execution_time_ms", results)
            self.assertIsInstance(results["execution_time_ms"], (int, float))
            self.assertGreaterEqual(results["execution_time_ms"], 0)

    def test_add_fuzzy_strategy_long_query_skips_content_fields(self):
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

    def test_add_fuzzy_strategy_short_query_includes_all_fields(self):
        builder = DocumentQueryBuilder("test")
        fields = [
            FieldConfig("abstract", boost=2.0, query_types=["fuzzy"]),
            FieldConfig("paper_title", boost=5.0, query_types=["fuzzy"]),
            FieldConfig("raw_authors.full_name", boost=3.0, query_types=["fuzzy"]),
            FieldConfig("renderable_text", boost=1.0, query_types=["fuzzy"]),
        ]
        builder.add_fuzzy_strategy(fields)
        query_dict = builder.build().to_dict()
        fields_in_query = query_dict["bool"]["should"][0]["multi_match"]["fields"]
        self.assertIn("paper_title^2", fields_in_query)
        self.assertIn("abstract^2", fields_in_query)
        self.assertIn("raw_authors.full_name^2", fields_in_query)
        self.assertIn("renderable_text", fields_in_query)

    def test_add_fuzzy_strategy_no_fuzzy_fields_returns_empty(self):
        builder = DocumentQueryBuilder("test")
        fields = [FieldConfig("title", boost=5.0, query_types=["phrase"])]
        builder.add_fuzzy_strategy(fields)
        query_dict = builder.build().to_dict()
        self.assertNotIn("multi_match", str(query_dict))


class PopularityConfigTests(TestCase):
    """Tests for PopularityConfig and popularity boosting."""

    def test_default_popularity_config_values(self):
        """Test default configuration values."""
        config = DEFAULT_POPULARITY_CONFIG
        self.assertTrue(config.enabled)
        self.assertEqual(config.weight, 1.0)
        self.assertEqual(config.boost_mode, "multiply")

    def test_popularity_config_custom_values(self):
        """Test custom configuration values."""
        config = PopularityConfig(enabled=False, weight=2.0, boost_mode="sum")
        self.assertFalse(config.enabled)
        self.assertEqual(config.weight, 2.0)
        self.assertEqual(config.boost_mode, "sum")

    def test_build_with_popularity_boost_enabled(self):
        """Test that popularity boost wraps query in function_score."""
        builder = DocumentQueryBuilder("machine learning")
        builder.add_simple_match_strategy(DocumentQueryBuilder.TITLE_FIELDS)

        config = PopularityConfig(enabled=True, weight=1.5)
        query = builder.build_with_popularity_boost(config)
        query_dict = query.to_dict()

        self.assertIn("function_score", query_dict)
        self.assertIn("query", query_dict["function_score"])
        self.assertIn("functions", query_dict["function_score"])
        self.assertEqual(len(query_dict["function_score"]["functions"]), 1)

        # Check the hot_score_v2 function
        func = query_dict["function_score"]["functions"][0]
        self.assertIn("field_value_factor", func)
        self.assertEqual(func["field_value_factor"]["field"], "hot_score_v2")
        self.assertEqual(func["field_value_factor"]["factor"], 1.5)
        self.assertEqual(func["field_value_factor"]["modifier"], "log1p")

    def test_build_with_popularity_boost_disabled(self):
        """Test that disabled config returns plain query without function_score."""
        builder = DocumentQueryBuilder("machine learning")
        builder.add_simple_match_strategy(DocumentQueryBuilder.TITLE_FIELDS)

        config = PopularityConfig(enabled=False)
        query = builder.build_with_popularity_boost(config)
        query_dict = query.to_dict()

        self.assertNotIn("function_score", query_dict)
        self.assertIn("bool", query_dict)

    def test_build_with_popularity_boost_zero_weight(self):
        """Test that zero weight returns plain query."""
        builder = DocumentQueryBuilder("machine learning")
        builder.add_simple_match_strategy(DocumentQueryBuilder.TITLE_FIELDS)

        config = PopularityConfig(enabled=True, weight=0)
        query = builder.build_with_popularity_boost(config)
        query_dict = query.to_dict()

        self.assertNotIn("function_score", query_dict)
        self.assertIn("bool", query_dict)

    def test_unified_query_builder_with_popularity(self):
        """Test UnifiedSearchQueryBuilder builds queries with popularity."""
        query_builder = UnifiedSearchQueryBuilder()
        query = query_builder.build_document_query_with_popularity("neural networks")
        query_dict = query.to_dict()

        self.assertIn("function_score", query_dict)
        self.assertIn("functions", query_dict["function_score"])

    def test_unified_query_builder_custom_popularity_config(self):
        """Test UnifiedSearchQueryBuilder respects custom popularity config."""
        custom_config = PopularityConfig(enabled=True, weight=3.0, boost_mode="sum")
        query_builder = UnifiedSearchQueryBuilder(popularity_config=custom_config)
        query = query_builder.build_document_query_with_popularity("deep learning")
        query_dict = query.to_dict()

        self.assertEqual(query_dict["function_score"]["boost_mode"], "sum")
        func = query_dict["function_score"]["functions"][0]
        self.assertEqual(func["field_value_factor"]["factor"], 3.0)


class UnifiedSearchViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/search/"

    def test_missing_query_parameter(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("q", response.data)

    def test_empty_query_parameter(self):
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("q", response.data)

    def test_invalid_sort_parameter(self):
        response = self.client.get(self.url, {"q": "test", "sort": "invalid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sort", response.data)

    def test_pagination_urls(self):
        service = UnifiedSearchService()
        request = Mock()
        request.path = "/api/search/"
        request.build_absolute_uri = lambda path: f"https://testserver{path}"

        url = service._build_page_url(request, "test query", 2, 10, "relevance")

        self.assertIn("https://testserver/api/search/", url)
        self.assertIn("q=test+query", url)
        self.assertIn("page=2", url)
        self.assertIn("page_size=10", url)
        self.assertIn("sort=relevance", url)
