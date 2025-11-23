"""
Tests for unified search functionality.
"""

from unittest.mock import MagicMock

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from search.services.unified_search_query_builder import (
    DocumentQueryBuilder,
    UnifiedSearchQueryBuilder,
)
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
        # Also check match queries with AND operator (from simple_match_strategy)
        and_nodes = [
            n
            for n in walk(qd)
            if isinstance(n, dict)
            and (
                (n.get("multi_match", {}).get("operator") == "and")
                or any(
                    isinstance(v, dict) and v.get("operator") == "and"
                    for v in n.values()
                    if isinstance(v, dict)
                )
            )
        ]
        or_nodes = [
            n
            for n in walk(qd)
            if isinstance(n, dict) and n.get("multi_match", {}).get("operator") == "or"
        ]
        # Should have at least one AND operator (from match queries or multi_match)
        # OR operators are also present (from author+title combo and other strategies)
        self.assertGreaterEqual(len(and_nodes), 1, "Should have AND operator queries")
        self.assertGreaterEqual(len(or_nodes), 1, "Should have OR operator queries")

        # Verify field boosting - check both multi_match and match queries
        # Match queries with AND operator are from simple_match_strategy
        # Multi_match queries with AND operator are from other strategies
        and_fields_lists = [
            n["multi_match"]["fields"]
            for n in and_nodes
            if "multi_match" in n and "fields" in n["multi_match"]
        ]
        # Also check match queries - they have field names as keys
        and_match_fields = [
            list(n.keys())
            for n in and_nodes
            if any(
                isinstance(v, dict) and v.get("operator") == "and"
                for v in n.values()
                if isinstance(v, dict)
            )
        ]
        # Flatten the match field lists
        all_and_fields = and_fields_lists + [
            [field] for fields in and_match_fields for field in fields
        ]
        # Verify we have some fields with boosting (title fields should be present)
        # Title fields are prioritized and should appear in AND queries
        has_title_fields = any(
            any(
                "paper_title" in str(field) or "title" in str(field) for field in fields
            )
            for fields in all_and_fields
        )
        self.assertTrue(
            has_title_fields,
            "Should have title fields (paper_title or title) in AND queries",
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


class AuthorNameSearchTests(TestCase):
    """Tests specifically for author name search functionality."""

    def setUp(self):
        self.query_builder = UnifiedSearchQueryBuilder()

    def test_author_last_name_only_query(self):
        """Test query for last name only (e.g., 'Smith')."""
        query = self.query_builder.build_document_query("Smith")
        qd = query.to_dict()

        # Helper to recursively find all match and multi_match queries
        def find_author_queries(node, results=None):
            if results is None:
                results = []
            if isinstance(node, dict):
                # Check for match queries on author fields
                for key, value in node.items():
                    if key in [
                        "raw_authors.full_name",
                        "raw_authors.last_name",
                        "raw_authors.first_name",
                        "authors.full_name",
                        "authors.last_name",
                        "authors.first_name",
                    ]:
                        results.append({"type": "match", "field": key, "query": value})
                # Check for multi_match queries
                if "multi_match" in node:
                    mm = node["multi_match"]
                    fields = mm.get("fields", [])
                    if any(
                        any(
                            author_field in f
                            for author_field in [
                                "authors.full_name",
                                "raw_authors.full_name",
                                "authors.last_name",
                                "raw_authors.last_name",
                                "authors.first_name",
                                "raw_authors.first_name",
                            ]
                        )
                        for f in fields
                    ):
                        results.append(mm)
                for v in node.values():
                    find_author_queries(v, results)
            elif isinstance(node, list):
                for item in node:
                    find_author_queries(item, results)
            return results

        author_queries = find_author_queries(qd)

        # Should have at least one query that includes author fields,
        # especially last_name
        author_fields_found = False
        last_name_found = False

        for aq in author_queries:
            if isinstance(aq, dict):
                if aq.get("type") == "match":
                    field = aq.get("field", "")
                    if "last_name" in field or "full_name" in field:
                        author_fields_found = True
                        if "last_name" in field:
                            last_name_found = True
                elif "multi_match" in str(aq):
                    fields = aq.get("fields", [])
                    if any(
                        "authors.full_name" in f
                        or "raw_authors.full_name" in f
                        or "authors.last_name" in f
                        or "raw_authors.last_name" in f
                        for f in fields
                    ):
                        author_fields_found = True
                        if any("last_name" in f for f in fields):
                            last_name_found = True

        self.assertTrue(
            author_fields_found,
            "Author fields should be included in at least one query clause",
        )
        self.assertTrue(
            last_name_found,
            "Author last_name fields should be included for last-name-only queries",
        )

    def test_author_full_name_query(self):
        """Test query for full name (e.g., 'John Smith')."""
        query = self.query_builder.build_document_query("John Smith")
        qd = query.to_dict()

        # Should be a bool query with should clauses
        self.assertIn("bool", qd)
        self.assertIn("should", qd["bool"])

        # Helper to check if author fields are included
        def check_author_fields(node):
            if isinstance(node, dict):
                if "multi_match" in node:
                    fields = node["multi_match"].get("fields", [])
                    if any(
                        "authors.full_name" in f or "raw_authors.full_name" in f
                        for f in fields
                    ):
                        return True
                for v in node.values():
                    if check_author_fields(v):
                        return True
            elif isinstance(node, list):
                for item in node:
                    if check_author_fields(item):
                        return True
            return False

        self.assertTrue(
            check_author_fields(qd),
            "Author fields should be included in the query",
        )

    def test_author_partial_name_query(self):
        """Test query for partial name (e.g., 'Smi' should match 'Smith')."""
        query = self.query_builder.build_document_query("Smi")
        qd = query.to_dict()

        # Helper to find all multi_match queries with author fields
        def find_author_queries(node, results=None):
            if results is None:
                results = []
            if isinstance(node, dict):
                if "multi_match" in node:
                    mm = node["multi_match"]
                    fields = mm.get("fields", [])
                    if any(
                        "authors.full_name" in f or "raw_authors.full_name" in f
                        for f in fields
                    ):
                        results.append(mm)
                for v in node.values():
                    find_author_queries(v, results)
            elif isinstance(node, list):
                for item in node:
                    find_author_queries(item, results)
            return results

        author_queries = find_author_queries(qd)

        # Should have at least one query that can handle partial matches
        # This could be fuzzy, prefix, or best_fields with OR operator
        has_partial_match_support = False
        for aq in author_queries:
            query_type = aq.get("type", "best_fields")
            operator = aq.get("operator", "or")
            fuzziness = aq.get("fuzziness")

            # Check if it supports partial matches
            if (
                query_type in ["best_fields", "most_fields"]
                or operator == "or"
                or fuzziness is not None
            ):
                has_partial_match_support = True
                break

        self.assertTrue(
            has_partial_match_support,
            "Query should support partial author name matches "
            "(prefix, fuzzy, or OR operator)",
        )

    def test_author_name_with_title_query(self):
        """Test query combining author name and title.

        Example: 'Smith machine learning'
        """
        query = self.query_builder.build_document_query("Smith machine learning")
        qd = query.to_dict()

        # Helper to find bool queries that require both author AND title match
        def find_author_title_bool_queries(node, results=None):
            if results is None:
                results = []
            if isinstance(node, dict):
                # Look for bool queries with must clauses that contain
                # both author and title matches
                if "bool" in node:
                    bool_query = node["bool"]
                    must_clauses = bool_query.get("must", [])
                    # Boost can be at node level or inside bool dict
                    boost = node.get("boost") or bool_query.get("boost", 1.0)

                    # Check if this is an author+title combo query
                    # It should have must clauses with author matches and title matches
                    has_author_match = False
                    has_title_match = False

                    for clause in must_clauses:
                        if isinstance(clause, dict) and "bool" in clause:
                            should_clauses = clause.get("bool", {}).get("should", [])
                            for should_clause in should_clauses:
                                if isinstance(should_clause, dict):
                                    # Check match queries inside should clauses
                                    # Match queries have structure: {"match": {"field_name": {...}}}
                                    # or directly: {"field_name": {...}}
                                    for key, value in should_clause.items():
                                        # If key is "match", value contains the field queries
                                        if key == "match" and isinstance(value, dict):
                                            for field_name in value.keys():
                                                if (
                                                    "authors" in field_name
                                                    or "raw_authors" in field_name
                                                ):
                                                    has_author_match = True
                                                if (
                                                    "title" in field_name
                                                    or "paper_title" in field_name
                                                ):
                                                    has_title_match = True
                                        # Otherwise, key might be the field name directly
                                        elif "authors" in key or "raw_authors" in key:
                                            has_author_match = True
                                        elif "title" in key or "paper_title" in key:
                                            has_title_match = True

                    if has_author_match and has_title_match and boost >= 10.0:
                        results.append({"boost": boost, "query": node})

                # Continue traversing
                for v in node.values():
                    find_author_title_bool_queries(v, results)
            elif isinstance(node, list):
                for item in node:
                    find_author_title_bool_queries(item, results)
            return results

        # Helper to find cross_fields queries
        def find_cross_fields_queries(node, results=None):
            if results is None:
                results = []
            if isinstance(node, dict):
                if "multi_match" in node:
                    mm = node["multi_match"]
                    if mm.get("type") == "cross_fields":
                        results.append(mm)
                for v in node.values():
                    find_cross_fields_queries(v, results)
            elif isinstance(node, list):
                for item in node:
                    find_cross_fields_queries(item, results)
            return results

        # Find author+title bool queries (should have boost >= 10.0)
        author_title_bool_queries = find_author_title_bool_queries(qd)

        # Find cross_fields queries
        cross_fields_queries = find_cross_fields_queries(qd)

        # Should have at least one author+title bool query with high boost
        self.assertGreater(
            len(author_title_bool_queries),
            0,
            "Should have bool query requiring both author AND title match",
        )

        # Verify the boost is high (15.0) to ensure ranking priority
        max_boost = max(
            (q.get("boost", 0) for q in author_title_bool_queries), default=0
        )
        self.assertGreaterEqual(
            max_boost,
            10.0,
            "Author+title combo query should have high boost (>=10.0) to rank first",
        )

        # Should also have cross_fields queries for flexible matching
        self.assertGreater(
            len(cross_fields_queries),
            0,
            "Should have cross_fields queries for author+title combinations",
        )

        # At least one cross_fields query should include author fields
        has_author_in_cross_fields = any(
            any(
                "authors.full_name" in f
                or "raw_authors.full_name" in f
                or "authors.last_name" in f
                or "raw_authors.last_name" in f
                for f in q.get("fields", [])
            )
            for q in cross_fields_queries
        )
        self.assertTrue(
            has_author_in_cross_fields,
            "At least one cross_fields query should include author fields",
        )

    def test_document_query_builder_author_fields_included(self):
        """Test that DocumentQueryBuilder includes all author fields in strategies."""
        builder = DocumentQueryBuilder("Smith")
        builder.add_fuzzy_strategy(
            DocumentQueryBuilder.TITLE_FIELDS
            + DocumentQueryBuilder.AUTHOR_FIELDS
            + DocumentQueryBuilder.CONTENT_FIELDS
        )
        query = builder.build()
        qd = query.to_dict()

        # Check that author fields (including last_name and first_name)
        # are in the fuzzy query
        def find_fuzzy_with_authors(node):
            if isinstance(node, dict):
                if "multi_match" in node:
                    mm = node["multi_match"]
                    if mm.get("fuzziness") is not None:
                        fields = mm.get("fields", [])
                        # Check for all author field types
                        author_field_patterns = [
                            "authors.full_name",
                            "raw_authors.full_name",
                            "authors.last_name",
                            "raw_authors.last_name",
                            "authors.first_name",
                            "raw_authors.first_name",
                        ]
                        if any(
                            any(pattern in f for pattern in author_field_patterns)
                            for f in fields
                        ):
                            return True
                for v in node.values():
                    if find_fuzzy_with_authors(v):
                        return True
            elif isinstance(node, list):
                for item in node:
                    if find_fuzzy_with_authors(item):
                        return True
            return False

        self.assertTrue(
            find_fuzzy_with_authors(qd),
            "Fuzzy strategy should include author fields "
            "(full_name, last_name, first_name)",
        )

        # Verify that AUTHOR_FIELDS includes the new fields
        author_fields = DocumentQueryBuilder.AUTHOR_FIELDS
        field_names = [field.name for field in author_fields]
        self.assertIn("raw_authors.last_name", field_names)
        self.assertIn("raw_authors.first_name", field_names)
        self.assertIn("authors.last_name", field_names)
        self.assertIn("authors.first_name", field_names)

    def test_author_fields_query_types(self):
        """Test that author fields have appropriate query types configured."""
        # Author fields should support partial matching
        author_fields = DocumentQueryBuilder.AUTHOR_FIELDS

        self.assertGreater(
            len(author_fields), 0, "Should have author fields configured"
        )

        # Verify all author fields have query_types that support partial matching
        for field in author_fields:
            query_types = field.query_types or []
            # Should support at least one of: fuzzy, prefix, or cross_fields
            has_partial_support = any(
                qt in ["fuzzy", "prefix", "cross_fields"] for qt in query_types
            )
            self.assertTrue(
                has_partial_support,
                f"Author field {field.name} should support partial matching "
                "(fuzzy/prefix/cross_fields)",
            )

        # Check that author fields are included in fuzzy strategy
        builder = DocumentQueryBuilder("test")
        builder.add_fuzzy_strategy(
            DocumentQueryBuilder.AUTHOR_FIELDS,
            operator="or",  # OR allows partial matches
        )
        query = builder.build()
        qd = query.to_dict()

        # Verify fuzzy query includes author fields (including last_name and first_name)
        def has_author_fuzzy(node):
            if isinstance(node, dict):
                if "multi_match" in node:
                    mm = node["multi_match"]
                    if mm.get("fuzziness") is not None:
                        fields = mm.get("fields", [])
                        author_field_patterns = [
                            "authors.full_name",
                            "raw_authors.full_name",
                            "authors.last_name",
                            "raw_authors.last_name",
                            "authors.first_name",
                            "raw_authors.first_name",
                        ]
                        return any(
                            any(pattern in f for pattern in author_field_patterns)
                            for f in fields
                        )
                for v in node.values():
                    if has_author_fuzzy(v):
                        return True
            elif isinstance(node, list):
                for item in node:
                    if has_author_fuzzy(item):
                        return True
            return False

        self.assertTrue(
            has_author_fuzzy(qd),
            "Author fields (including last_name and first_name) should be "
            "included in fuzzy queries for partial matching",
        )

    def test_author_title_combination_priority(self):
        """Test that author+title combination strategy is prioritized (added first)."""
        # Build a query that should trigger author+title combination
        query = self.query_builder.build_document_query("gordon protein folding")
        qd = query.to_dict()

        # The query should be a bool query with should clauses
        self.assertIn("bool", qd)
        self.assertIn("should", qd["bool"])
        should_clauses = qd["bool"]["should"]

        # Find the author+title bool query (should have boost >= 10.0)
        def find_author_title_combo(clauses):
            for i, clause in enumerate(clauses):
                if isinstance(clause, dict) and "bool" in clause:
                    bool_query = clause["bool"]
                    must_clauses = bool_query.get("must", [])
                    # Boost can be at clause level or inside bool dict
                    boost = clause.get("boost") or bool_query.get("boost", 1.0)

                    # Check if this requires both author and title match
                    has_author = False
                    has_title = False

                    for must_clause in must_clauses:
                        if isinstance(must_clause, dict) and "bool" in must_clause:
                            should_clauses_inner = must_clause.get("bool", {}).get(
                                "should", []
                            )
                            for sc in should_clauses_inner:
                                if isinstance(sc, dict):
                                    # Check match queries - structure: {"match": {"field_name": {...}}}
                                    for key, value in sc.items():
                                        if key == "match" and isinstance(value, dict):
                                            # value contains field_name -> query_params mapping
                                            for field_name in value.keys():
                                                if (
                                                    "authors" in field_name
                                                    or "raw_authors" in field_name
                                                ):
                                                    has_author = True
                                                if (
                                                    "title" in field_name
                                                    or "paper_title" in field_name
                                                ):
                                                    has_title = True
                                        # Also check if key is directly a field name
                                        elif "authors" in key or "raw_authors" in key:
                                            has_author = True
                                        elif "title" in key or "paper_title" in key:
                                            has_title = True

                    if has_author and has_title and boost >= 10.0:
                        return i, boost

            return None, 0

        combo_index, combo_boost = find_author_title_combo(should_clauses)

        # Should find the author+title combo query
        self.assertIsNotNone(
            combo_index,
            "Should have author+title combination query with high boost",
        )
        self.assertGreaterEqual(
            combo_boost,
            10.0,
            "Author+title combo should have boost >= 10.0 to rank first",
        )

        # The author+title combo should be early in the should clauses
        # (Ideally first, but at least in the first few)
        self.assertLess(
            combo_index,
            5,
            "Author+title combo query should be prioritized (early in should clauses)",
        )

    def test_query_truncation_for_long_queries(self):
        """Test that very long queries are truncated for author+title combo."""
        # Create a query with more than 7 words
        long_query = (
            "gordon protein folding machine learning neural networks "
            "deep learning artificial intelligence"
        )
        query = self.query_builder.build_document_query(long_query)
        qd = query.to_dict()

        # Helper to find the author+title bool query and extract its query string
        def find_author_title_query_string(node, results=None):
            if results is None:
                results = []
            if isinstance(node, dict):
                if "bool" in node:
                    bool_query = node["bool"]
                    must_clauses = bool_query.get("must", [])
                    # Boost can be at node level or inside bool dict
                    boost = node.get("boost") or bool_query.get("boost", 1.0)

                    # Check if this is the author+title combo query
                    has_author = False
                    has_title = False
                    query_strings = []

                    for must_clause in must_clauses:
                        if isinstance(must_clause, dict) and "bool" in must_clause:
                            should_clauses_inner = must_clause.get("bool", {}).get(
                                "should", []
                            )
                            for sc in should_clauses_inner:
                                if isinstance(sc, dict):
                                    # Check match queries - structure: {"match": {"field_name": {...}}}
                                    for key, value in sc.items():
                                        if key == "match" and isinstance(value, dict):
                                            # value contains field_name -> query_params mapping
                                            for (
                                                field_name,
                                                field_query,
                                            ) in value.items():
                                                if (
                                                    "authors" in field_name
                                                    or "raw_authors" in field_name
                                                ):
                                                    has_author = True
                                                if (
                                                    "title" in field_name
                                                    or "paper_title" in field_name
                                                ):
                                                    has_title = True
                                                # Extract query string
                                                if (
                                                    isinstance(field_query, dict)
                                                    and "query" in field_query
                                                ):
                                                    query_strings.append(
                                                        field_query["query"]
                                                    )
                                        # Also check if key is directly a field name
                                        elif "authors" in key or "raw_authors" in key:
                                            has_author = True
                                        elif "title" in key or "paper_title" in key:
                                            has_title = True

                    if has_author and has_title and boost >= 10.0:
                        results.extend(query_strings)

                # Continue traversing
                for v in node.values():
                    find_author_title_query_string(v, results)
            elif isinstance(node, list):
                for item in node:
                    find_author_title_query_string(item, results)
            return results

        query_strings = find_author_title_query_string(qd)

        # Should have found query strings from the author+title combo
        self.assertGreater(
            len(query_strings),
            0,
            "Should find query strings in author+title combo query",
        )

        # All query strings should be truncated to 7 words max
        for query_str in query_strings:
            word_count = len(query_str.split())
            self.assertLessEqual(
                word_count,
                7,
                f"Author+title combo query should be truncated to 7 words, "
                f"but found {word_count} words in: {query_str}",
            )

        # Verify the truncated query contains the first 7 words
        expected_words = long_query.split()[:7]
        expected_truncated = " ".join(expected_words)
        # At least one query string should match the expected truncation
        self.assertTrue(
            any(qs == expected_truncated for qs in query_strings),
            f"Expected truncated query '{expected_truncated}' not found. "
            f"Found: {query_strings}",
        )
