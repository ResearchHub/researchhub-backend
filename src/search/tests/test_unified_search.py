"""
Tests for unified search functionality.
"""

from unittest.mock import MagicMock, patch

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
        """Test document query building with proper boosting."""
        query = self.service._build_document_query("machine learning")
        self.assertIsNotNone(query)
        # Query should have the search term
        self.assertEqual(query.to_dict()["multi_match"]["query"], "machine learning")
        # Verify field boosting
        fields = query.to_dict()["multi_match"]["fields"]
        self.assertIn("paper_title^5", fields)
        self.assertIn("title^5", fields)
        self.assertIn("abstract^2", fields)

    def test_build_person_query(self):
        """Test person query building with proper boosting."""
        query = self.service._build_person_query("Jane Doe")
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
        self.assertTrue(any("-created_date" in str(s) for s in sort_dict))

    def test_apply_sort_hot(self):
        """Test hot sort."""
        from opensearchpy import Search

        search = Search()
        sorted_search = self.service._apply_sort(search, "hot")
        sort_dict = sorted_search.to_dict().get("sort", [])
        # Should sort by hot_score descending
        self.assertTrue(any("hot_score" in str(s) for s in sort_dict))

    def test_apply_sort_upvoted(self):
        """Test upvoted sort."""
        from opensearchpy import Search

        search = Search()
        sorted_search = self.service._apply_sort(search, "upvoted")
        sort_dict = sorted_search.to_dict().get("sort", [])
        # Should sort by score descending
        has_score = any("score" in str(s) and "hot" not in str(s) for s in sort_dict)
        self.assertTrue(has_score)

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
        # Should have years, hubs, and content_types aggregations
        self.assertIn("years", agg_dict)
        self.assertIn("hubs", agg_dict)
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
        mock_hit.hot_score = 100
        mock_hit.score = 50
        mock_hit.raw_authors = [{"full_name": "John Doe"}]
        mock_hit.doi = "10.1234/test"
        mock_hit.citations = 42
        mock_hit.is_open_access = True
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
        self.assertEqual(result["doi"], "10.1234/test")
        self.assertEqual(result["citations"], 42)
        self.assertTrue(result["is_open_access"])
        self.assertEqual(len(result["hubs"]), 1)

    def test_process_document_results_post(self):
        """Test processing post document results."""
        # Mock response
        mock_hit = MagicMock()
        mock_hit.id = "456"
        mock_hit.meta.index = "post"
        mock_hit.meta.score = 8.5
        mock_hit.title = "Test Post"
        mock_hit.created_date = "2024-01-01"
        mock_hit.hot_score = 80
        mock_hit.score = 30
        mock_hit.authors = [{"full_name": "Jane Smith"}]
        mock_hit.slug = "test-post"
        mock_hit.document_type = "DISCUSSION"
        mock_hit.hubs = []
        mock_hit.meta.highlight = None

        mock_response = MagicMock()
        mock_response.hits = [mock_hit]

        results = self.service._process_document_results(mock_response)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result["id"], "456")
        self.assertEqual(result["type"], "post")
        self.assertEqual(result["title"], "Test Post")
        self.assertEqual(result["slug"], "test-post")
        self.assertEqual(result["document_type"], "DISCUSSION")

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

        mock_bucket_hub = MagicMock()
        mock_bucket_hub.key = "Neuroscience"
        mock_bucket_hub.doc_count = 30

        mock_bucket_type = MagicMock()
        mock_bucket_type.key = "paper"
        mock_bucket_type.doc_count = 100

        mock_aggs = MagicMock()
        mock_aggs.years.buckets = [mock_bucket_year]
        mock_aggs.hubs.buckets = [mock_bucket_hub]
        mock_aggs.content_types.buckets = [mock_bucket_type]

        mock_response = MagicMock()
        mock_response.aggregations = mock_aggs

        aggregations = self.service._process_aggregations(mock_response)

        self.assertIn("years", aggregations)
        self.assertIn("hubs", aggregations)
        self.assertIn("content_types", aggregations)
        self.assertEqual(aggregations["years"][0]["key"], "2024")
        self.assertEqual(aggregations["hubs"][0]["key"], "Neuroscience")


class UnifiedSearchViewTests(TestCase):
    """Tests for UnifiedSearchView."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/search/"

    def test_missing_query_parameter(self):
        """Test that missing query parameter returns 400."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_empty_query_parameter(self):
        """Test that empty query parameter returns 400."""
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_invalid_sort_parameter(self):
        """Test that invalid sort parameter returns 400."""
        response = self.client.get(self.url, {"q": "test", "sort": "invalid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    @patch("search.views.unified_search.UnifiedSearchService")
    def test_valid_search_request(self, mock_service_class):
        """Test successful search request."""
        # Mock service response
        mock_service = mock_service_class.return_value
        mock_service.search.return_value = {
            "count": 10,
            "documents": [
                {
                    "id": 1,
                    "type": "paper",
                    "title": "Test Paper",
                    "snippet": "Test snippet",
                    "matched_field": "title",
                    "authors": ["John Doe"],
                    "created_date": "2024-01-01",
                    "hot_score": 100,
                    "score": 50,
                    "_search_score": 10.5,
                    "hubs": [],
                    "doi": "10.1234/test",
                    "citations": 42,
                    "is_open_access": True,
                }
            ],
            "people": [],
            "aggregations": {},
        }

        response = self.client.get(self.url, {"q": "machine learning"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("documents", response.data)
        self.assertIn("people", response.data)
        self.assertIn("count", response.data)

    @patch("search.views.unified_search.UnifiedSearchService")
    def test_pagination_parameters(self, mock_service_class):
        """Test that pagination parameters are correctly passed."""
        mock_service = mock_service_class.return_value
        mock_service.search.return_value = {
            "count": 0,
            "documents": [],
            "people": [],
            "aggregations": {},
        }

        # Test with custom page and page_size
        self.client.get(self.url, {"q": "test", "page": "2", "page_size": "20"})
        mock_service.search.assert_called_with(
            query="test",
            page=2,
            page_size=20,
            sort="relevance",
        )

    @patch("search.views.unified_search.UnifiedSearchService")
    def test_sort_parameter(self, mock_service_class):
        """Test that sort parameter is correctly passed."""
        mock_service = mock_service_class.return_value
        mock_service.search.return_value = {
            "count": 0,
            "documents": [],
            "people": [],
            "aggregations": {},
        }

        # Test with hot sort
        self.client.get(self.url, {"q": "test", "sort": "hot"})
        mock_service.search.assert_called_with(
            query="test",
            page=1,
            page_size=10,
            sort="hot",
        )

    @patch("search.views.unified_search.UnifiedSearchService")
    def test_invalid_pagination_parameters(self, mock_service_class):
        """Test that invalid pagination parameters are handled."""
        mock_service = mock_service_class.return_value
        mock_service.search.return_value = {
            "count": 0,
            "documents": [],
            "people": [],
            "aggregations": {},
        }

        # Test with negative page
        self.client.get(self.url, {"q": "test", "page": "-1"})
        # Should default to page 1
        call_args = mock_service.search.call_args
        self.assertEqual(call_args[1]["page"], 1)

        # Test with page_size > 100
        self.client.get(self.url, {"q": "test", "page_size": "200"})
        # Should cap at 100
        call_args = mock_service.search.call_args
        self.assertEqual(call_args[1]["page_size"], 100)

    @patch("search.views.unified_search.UnifiedSearchService")
    def test_service_exception_handling(self, mock_service_class):
        """Test that service exceptions are handled gracefully."""
        mock_service = mock_service_class.return_value
        mock_service.search.side_effect = Exception("Test error")

        response = self.client.get(self.url, {"q": "test"})
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("error", response.data)
