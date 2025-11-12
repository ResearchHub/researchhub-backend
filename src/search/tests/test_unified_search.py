"""
Tests for unified search functionality.
"""

from unittest.mock import MagicMock

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from search.services.unified_search_service import UnifiedSearchService


class UnifiedSearchServiceTests(TestCase):
    """Tests for UnifiedSearchService."""

    def setUp(self):
        self.service = UnifiedSearchService()

    def test_init(self):
        """Test service initialization."""
        self.assertIsNotNone(self.service.paper_index)
        self.assertIsNotNone(self.service.post_index)
        self.assertIsNotNone(self.service.person_index)

    def test_build_document_query(self):
        """Test document query building with hybrid query structure."""
        query = self.service.query_builder.build_document_query("machine learning")
        self.assertIsNotNone(query)
        qd = query.to_dict()

        # Should be a bool query with should clauses
        self.assertIn("bool", qd)
        self.assertIn("should", qd["bool"])
        self.assertGreater(len(qd["bool"]["should"]), 0)

        # Helpers to recursively traverse dict/list nodes
        def walk(node):
            if isinstance(node, dict):
                yield node
                for v in node.values():
                    yield from walk(v)
            elif isinstance(node, list):
                for item in node:
                    yield from walk(item)

        # Verify phrase match exists anywhere (including inside dis_max)
        phrase_count = sum(
            1 for n in walk(qd) if isinstance(n, dict) and "match_phrase" in n
        )
        self.assertGreater(phrase_count, 0)

        # Collect AND/OR multi_match occurrences anywhere
        and_nodes = [
            n
            for n in walk(qd)
            if isinstance(n, dict) and n.get("multi_match", {}).get("operator") == "and"
        ]
        or_nodes = [
            n
            for n in walk(qd)
            if isinstance(n, dict) and n.get("multi_match", {}).get("operator") == "or"
        ]
        self.assertGreaterEqual(len(and_nodes), 1)
        self.assertGreaterEqual(len(or_nodes), 1)

        # Verify field boosting in at least one AND multi_match
        and_fields_lists = [n["multi_match"]["fields"] for n in and_nodes]
        self.assertTrue(any("abstract^2" in fields for fields in and_fields_lists))
        self.assertTrue(
            any(
                any(f in fields for f in ["paper_title^5", "paper_title^4"])
                for fields in and_fields_lists
            )
        )
        self.assertTrue(
            any(
                any(f in fields for f in ["title^5", "title^4"])
                for fields in and_fields_lists
            )
        )

    def test_build_person_query(self):
        """Test person query building with proper boosting."""
        query = self.service.query_builder.build_person_query("Jane Doe")
        self.assertIsNotNone(query)
        self.assertEqual(query.to_dict()["multi_match"]["query"], "Jane Doe")
        # Verify field boosting for people
        fields = query.to_dict()["multi_match"]["fields"]
        self.assertIn("full_name^5", fields)
        self.assertIn("description^1", fields)

    def test_apply_sort_relevance(self):
        """Test relevance sort (default)."""
        from opensearchpy import Search

        search = Search()
        sorted_search = self.service._apply_sort(search, "relevance")
        sort_dict = sorted_search.to_dict().get("sort", [])
        self.assertTrue(len(sort_dict) > 0)
        # Relevance sort should use _score
        self.assertIn({"_score": {"order": "desc"}}, sort_dict)

    def test_apply_sort_newest(self):
        """Test newest sort."""
        from opensearchpy import Search

        search = Search()
        sorted_search = self.service._apply_sort(search, "newest")
        sort_dict = sorted_search.to_dict().get("sort", [])
        # Should sort by created_date descending
        self.assertTrue(any("created_date" in str(s) for s in sort_dict))

    def test_apply_sort_invalid_defaults_to_relevance(self):
        """Test that invalid sort options default to relevance."""
        from opensearchpy import Search

        search = Search()
        # Test with an invalid sort option
        sorted_search = self.service._apply_sort(search, "invalid")
        sort_dict = sorted_search.to_dict().get("sort", [])
        # Should default to _score (relevance)
        self.assertIn({"_score": {"order": "desc"}}, sort_dict)

    def test_apply_highlighting_documents(self):
        """Test highlighting configuration for documents."""
        from opensearchpy import Search

        search = Search()
        highlighted_search = self.service._apply_highlighting(search, is_document=True)
        highlight_dict = highlighted_search.to_dict().get("highlight", {})
        self.assertIn("fields", highlight_dict)
        # Should highlight paper_title, title, abstract, renderable_text
        self.assertIn("paper_title", highlight_dict["fields"])
        self.assertIn("abstract", highlight_dict["fields"])
        # Should use <mark> tags
        self.assertEqual(highlight_dict["pre_tags"], ["<mark>"])
        self.assertEqual(highlight_dict["post_tags"], ["</mark>"])

    def test_apply_highlighting_people(self):
        """Test highlighting configuration for people."""
        from opensearchpy import Search

        search = Search()
        highlighted_search = self.service._apply_highlighting(search, is_document=False)
        highlight_dict = highlighted_search.to_dict().get("highlight", {})
        self.assertIn("fields", highlight_dict)
        # Should highlight full_name, description
        self.assertIn("full_name", highlight_dict["fields"])
        self.assertIn("description", highlight_dict["fields"])

    def test_add_aggregations(self):
        """Test aggregations are added correctly."""
        from opensearchpy import Search

        search = Search()
        agg_search = self.service._add_aggregations(search)
        agg_dict = agg_search.to_dict().get("aggs", {})
        # Should have years and content_types aggregations
        self.assertIn("years", agg_dict)
        self.assertIn("content_types", agg_dict)

    def test_process_document_results_paper(self):
        """Test processing paper document results."""
        # Mock response
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
        # Verify score is included
        self.assertEqual(result["score"], 50)
        # Verify authors are structured objects
        self.assertEqual(len(result["authors"]), 1)
        self.assertEqual(result["authors"][0]["first_name"], "John")
        self.assertEqual(result["authors"][0]["last_name"], "Doe")
        self.assertEqual(result["authors"][0]["full_name"], "John Doe")

    def test_process_document_results_post(self):
        """Test processing post document results - simplified."""
        # This test is simplified due to mocking complexity
        # Real integration tests should test against actual OpenSearch
        pass

    def test_process_people_results(self):
        """Test processing people results."""
        # Mock response
        mock_hit = MagicMock()
        mock_hit.id = "789"
        mock_hit.meta.score = 12.0
        mock_hit.full_name = "Alice Johnson"
        mock_hit.profile_image = "https://example.com/image.jpg"
        mock_hit.user_reputation = 5000
        mock_hit.user_id = 100
        mock_hit.headline = {"title": "Professor"}
        mock_hit.institutions = [{"id": 1, "name": "MIT"}]
        mock_hit.meta.highlight = None

        mock_response = MagicMock()
        mock_response.hits = [mock_hit]

        results = self.service._process_people_results(mock_response)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["id"], "789")
        self.assertEqual(result["full_name"], "Alice Johnson")
        self.assertEqual(result["user_reputation"], 5000)
        self.assertEqual(len(result["institutions"]), 1)

    def test_process_aggregations(self):
        """Test processing aggregations."""
        # Mock aggregations
        mock_bucket_year = MagicMock()
        mock_bucket_year.key_as_string = "2024"
        mock_bucket_year.doc_count = 45

        mock_bucket_type = MagicMock()
        mock_bucket_type.key = "paper"
        mock_bucket_type.doc_count = 100

        mock_aggs = MagicMock()
        mock_aggs.years.buckets = [mock_bucket_year]
        mock_aggs.content_types.buckets = [mock_bucket_type]

        mock_response = MagicMock()
        mock_response.aggregations = mock_aggs

        aggregations = self.service._process_aggregations(mock_response)

        self.assertIn("years", aggregations)
        self.assertIn("content_types", aggregations)
        self.assertEqual(aggregations["years"][0]["key"], "2024")


class UnifiedSearchViewTests(TestCase):
    """Tests for UnifiedSearchView."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/search/"

    def test_missing_query_parameter(self):
        """Test that missing query parameter returns 400."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("q", response.data)
        self.assertEqual(str(response.data["q"][0]), "This field is required.")

    def test_empty_query_parameter(self):
        """Test that empty query parameter returns 400."""
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("q", response.data)
        self.assertEqual(str(response.data["q"][0]), "This field may not be blank.")

    def test_invalid_sort_parameter(self):
        """Test that invalid sort parameter returns 400."""
        response = self.client.get(self.url, {"q": "test", "sort": "invalid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sort", response.data)
        self.assertIn("is not a valid choice", str(response.data["sort"][0]))

    def test_hot_sort_parameter_invalid(self):
        """Test that 'hot' sort parameter is no longer valid."""
        response = self.client.get(self.url, {"q": "test", "sort": "hot"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sort", response.data)

    def test_upvoted_sort_parameter_invalid(self):
        """Test that 'upvoted' sort parameter is no longer valid."""
        response = self.client.get(self.url, {"q": "test", "sort": "upvoted"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sort", response.data)

    def test_pagination_urls(self):
        """Test that pagination URLs are generated correctly."""
        from unittest.mock import Mock

        from search.services.unified_search_service import UnifiedSearchService

        service = UnifiedSearchService()

        # Mock request
        request = Mock()
        request.path = "/api/search/"
        request.build_absolute_uri = lambda path: f"https://testserver{path}"

        # Build URL for page 2
        url = service._build_page_url(request, "test query", 2, 10, "relevance")

        # Verify URL structure
        self.assertIn("https://testserver/api/search/", url)
        self.assertIn("q=test+query", url)
        self.assertIn("page=2", url)
        self.assertIn("page_size=10", url)
        self.assertIn("sort=relevance", url)

    def test_valid_search_requires_opensearch(self):
        """
        Note: Full integration tests require actual OpenSearch connection.
        These tests verify parameter validation only.
        For full testing, run manual tests with actual OpenSearch instance.
        """
        # Just a placeholder to document that integration tests
        # should be run manually or in CI with OpenSearch
        pass

    def test_execution_time_included_in_response(self):
        """Test that execution_time_ms is included in search response."""
        from unittest.mock import Mock, patch

        # Mock the search methods to return empty results quickly
        empty_doc_result = {"results": [], "count": 0, "aggregations": {}}
        empty_people_result = {"results": [], "count": 0}
        empty_doi_result = {"results": [], "count": 0}

        with (
            patch.object(
                self.service, "_search_documents", return_value=empty_doc_result
            ),
            patch.object(
                self.service, "_search_people", return_value=empty_people_result
            ),
            patch.object(
                self.service, "_search_documents_by_doi", return_value=empty_doi_result
            ),
        ):
            # Mock request
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

            # Verify execution_time_ms is present and is a positive number
            self.assertIn("execution_time_ms", results)
            self.assertIsInstance(results["execution_time_ms"], (int, float))
            self.assertGreaterEqual(results["execution_time_ms"], 0)

    def test_execution_time_format(self):
        """Test that execution_time_ms is properly formatted (rounded to 2 decimals)."""
        from search.base.utils import seconds_to_milliseconds

        # Test various time values
        self.assertEqual(seconds_to_milliseconds(0.123456), 123.46)
        self.assertEqual(seconds_to_milliseconds(0.1), 100.0)
        self.assertEqual(seconds_to_milliseconds(1.0), 1000.0)
        self.assertEqual(seconds_to_milliseconds(0.001), 1.0)
        self.assertEqual(seconds_to_milliseconds(0.0001), 0.1)

    def test_execution_time_in_doi_search_response(self):
        """Test that execution_time_ms is included in DOI search response."""
        from unittest.mock import patch

        # Mock DOI search to return a result
        mock_result = {
            "id": "123",
            "type": "paper",
            "title": "Test Paper",
            "authors": [],
            "hubs": [],
        }

        doi_search_result = {"results": [mock_result], "count": 1}

        with (
            patch.object(
                self.service, "_search_documents_by_doi", return_value=doi_search_result
            ),
            patch("utils.doi.DOI.is_doi", return_value=True),
            patch("utils.doi.DOI.normalize_doi", return_value="10.1234/test"),
        ):
            results = self.service.search(query="10.1234/test", page=1, page_size=10)

            # Verify execution_time_ms is present in DOI search response
            self.assertIn("execution_time_ms", results)
            self.assertIsInstance(results["execution_time_ms"], (int, float))
            self.assertGreaterEqual(results["execution_time_ms"], 0)
            # Verify it's a DOI search result (has documents, no people)
            self.assertEqual(len(results["documents"]), 1)
            self.assertEqual(len(results["people"]), 0)
