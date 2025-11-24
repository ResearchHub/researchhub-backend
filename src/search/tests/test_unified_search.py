from unittest.mock import MagicMock, Mock, patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from search.services.unified_search_service import UnifiedSearchService


class UnifiedSearchServiceTests(TestCase):
    def setUp(self):
        self.service = UnifiedSearchService()

    def test_init(self):
        self.assertIsNotNone(self.service.paper_index)
        self.assertIsNotNone(self.service.post_index)
        self.assertIsNotNone(self.service.person_index)

    def test_build_document_query(self):
        query = self.service.query_builder.build_document_query("machine learning")
        self.assertIsNotNone(query)
        qd = query.to_dict()
        self.assertIn("bool", qd)
        self.assertIn("should", qd["bool"])
        self.assertGreater(len(qd["bool"]["should"]), 0)

    def test_build_person_query(self):
        query = self.service.query_builder.build_person_query("Jane Doe")
        self.assertIsNotNone(query)
        self.assertEqual(query.to_dict()["multi_match"]["query"], "Jane Doe")
        fields = query.to_dict()["multi_match"]["fields"]
        self.assertIn("full_name^5", fields)
        self.assertIn("description^1", fields)

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
        highlighted_search = self.service._apply_highlighting(search, is_document=True)
        highlight_dict = highlighted_search.to_dict().get("highlight", {})
        self.assertIn("fields", highlight_dict)
        self.assertIn("paper_title", highlight_dict["fields"])
        self.assertIn("abstract", highlight_dict["fields"])
        self.assertEqual(highlight_dict["pre_tags"], ["<mark>"])
        self.assertEqual(highlight_dict["post_tags"], ["</mark>"])

    def test_apply_highlighting_people(self):
        from opensearchpy import Search

        search = Search()
        highlighted_search = self.service._apply_highlighting(search, is_document=False)
        highlight_dict = highlighted_search.to_dict().get("highlight", {})
        self.assertIn("fields", highlight_dict)
        self.assertIn("full_name", highlight_dict["fields"])
        self.assertIn("description", highlight_dict["fields"])

    def test_add_aggregations(self):
        from opensearchpy import Search

        search = Search()
        agg_search = self.service._add_aggregations(search)
        agg_dict = agg_search.to_dict().get("aggs", {})
        self.assertIn("years", agg_dict)
        self.assertIn("content_types", agg_dict)

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

    def test_process_people_results(self):
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
