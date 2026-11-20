from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from opensearchpy import Search
from rest_framework import status
from rest_framework.test import APIClient


def _suggest_response(options):
    return MagicMock(
        **{"suggest.to_dict.return_value": {"suggestions": [{"options": options}]}}
    )


def _sized_suggest_execute(options_by_field):
    """Fake Search.execute that honors the completion size like OpenSearch."""

    def execute(search):
        completion = search.to_dict()["suggest"]["suggestions"]["completion"]
        options = options_by_field.get(completion["field"], [])
        return _suggest_response(options[: completion["size"]])

    return execute


def _user_options(count, score):
    return [
        {"_score": score, "_source": {"id": i, "full_name": f"User {i}"}}
        for i in range(count)
    ]


def _post_options(count, score):
    return [
        {"_score": score, "_source": {"id": i, "title": f"Post {i}"}}
        for i in range(count)
    ]


class SuggestViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("suggest")

    @patch("opensearchpy.Search.execute")
    def test_empty_results(self, mock_es_execute):
        """Test handling of empty search results"""

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

    @patch("opensearchpy.Search.execute")
    def test_error_handling(self, mock_es_execute):
        """Test that search errors are handled gracefully"""
        # Mock Elasticsearch error - caught and logged
        mock_es_execute.side_effect = Exception("Elasticsearch error")

        response = self.client.get(self.url + "?q=test")
        # With graceful error handling, we return empty results with 200
        # instead of failing with 500
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return empty results when search fails
        self.assertEqual(response.data, [])

    @patch("opensearchpy.Search.execute")
    def test_invalid_index_parameter(self, mock_es_execute):
        """Test handling of invalid index parameter"""
        response = self.client.get(self.url + "?q=test&index=invalid_index")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid indexes: invalid_index", response.data["error"])
        self.assertIn(
            "Available indexes:", response.data["error"]
        )  # Should list available indexes

    @patch("opensearchpy.Search.execute")
    def test_default_indexes(self, mock_es_execute):
        """Test that the user and post indexes are searched when no index is given"""
        # Arrange
        user_options = [{"_score": 1.0, "_source": {"id": 1, "full_name": "Test User"}}]
        post_options = [{"_score": 1.0, "_source": {"id": 2, "title": "Test Post"}}]
        mock_es_execute.side_effect = [
            _suggest_response(user_options),
            _suggest_response(post_options),
        ]

        # Act
        response = self.client.get(self.url + "?q=test")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entity_types = {result["entity_type"] for result in response.data}
        self.assertEqual(entity_types, {"user", "post"})

    @patch.object(Search, "execute", autospec=True)
    def test_default_indexes_backfill_when_one_index_is_empty(self, mock_es_execute):
        # Arrange
        mock_es_execute.side_effect = _sized_suggest_execute(
            {"suggestion_phrases": _post_options(12, score=1.0)}
        )

        # Act
        response = self.client.get(self.url + "?q=test")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)
        self.assertTrue(all(r["entity_type"] == "post" for r in response.data))

    @patch.object(Search, "execute", autospec=True)
    def test_default_indexes_backfill_when_one_index_is_short(self, mock_es_execute):
        # Arrange
        mock_es_execute.side_effect = _sized_suggest_execute(
            {
                "full_name_suggest": _user_options(3, score=100.0),
                "suggestion_phrases": _post_options(12, score=1.0),
            }
        )

        # Act
        response = self.client.get(self.url + "?q=test")

        # Assert
        entity_types = [r["entity_type"] for r in response.data]
        self.assertEqual(entity_types.count("user"), 3)
        self.assertEqual(entity_types.count("post"), 7)

    @patch.object(Search, "execute", autospec=True)
    def test_default_indexes_cap_each_type_at_its_share(self, mock_es_execute):
        # Arrange
        mock_es_execute.side_effect = _sized_suggest_execute(
            {
                "full_name_suggest": _user_options(12, score=100.0),
                "suggestion_phrases": _post_options(12, score=1.0),
            }
        )

        # Act
        response = self.client.get(self.url + "?q=test")

        # Assert
        entity_types = [r["entity_type"] for r in response.data]
        self.assertEqual(entity_types.count("user"), 5)
        self.assertEqual(entity_types.count("post"), 5)

    @patch("opensearchpy.Search.execute")
    def test_empty_query_sanitization(self, mock_es_execute):
        """Test that empty spaces in query are handled properly"""
        # Try with just spaces
        response = self.client.get(self.url + "?q=   ")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Search query is required")

        # Try with empty string
        response = self.client.get(self.url + "?q=")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Search query is required")

    @patch("opensearchpy.Search.execute")
    def test_limit_parameter(self, mock_es_execute):
        """Test that limit parameter restricts the number of results"""
        # Create numerous results
        post_options = [
            {"_score": 1.0, "_source": {"id": i, "title": f"Test Post {i}"}}
            for i in range(15)
        ]
        mock_es_execute.return_value = _suggest_response(post_options)

        # Test with default limit (10)
        response = self.client.get(self.url + "?q=test&index=post")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)  # Should be limited to 10 results

        # Test with custom limit
        response = self.client.get(self.url + "?q=test&index=post&limit=5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 5)  # Should be limited to 5 results

        # Test with limit higher than available results
        response = self.client.get(self.url + "?q=test&index=post&limit=20")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 15)  # Should return all 15 available

        # Test with invalid limit
        response = self.client.get(self.url + "?q=test&index=post&limit=invalid")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)  # Should use default of 10

    @patch("opensearchpy.Search.execute")
    def test_hub_index_search(self, mock_es_execute):
        """Test searching in the hub index"""

        # Mock Elasticsearch response for hub index
        hub_options = [
            {
                "_score": 1.0,
                "_source": {
                    "id": 1,
                    "name": "Computer Science",
                    "slug": "computer-science",
                    "description": (
                        "Computer science is the study of computation and information."
                    ),
                    "paper_count": 150,
                    "discussion_count": 45,
                },
            },
            {
                "_score": 0.8,
                "_source": {
                    "id": 2,
                    "name": "Computational Biology",
                    "slug": "computational-biology",
                    "description": (
                        "Computational biology involves the development and"
                        " application of data-analytical methods."
                    ),
                    "paper_count": 75,
                    "discussion_count": 20,
                },
            },
        ]

        # Mock Elasticsearch response
        class MockSuggest:
            def to_dict(self):
                return {"suggestions": [{"options": hub_options}]}

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        # Test searching hubs
        response = self.client.get(self.url + "?q=comp&index=hub")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify we got the expected results
        self.assertEqual(len(response.data), 2)

        # Verify all results are hubs
        for result in response.data:
            self.assertEqual(result["entity_type"], "hub")
            self.assertEqual(result["source"], "researchhub")

        # Check specific values
        self.assertEqual(response.data[0]["display_name"], "Computer Science")
        self.assertEqual(response.data[0]["slug"], "computer-science")
        self.assertEqual(response.data[0]["paper_count"], 150)
        self.assertEqual(response.data[1]["display_name"], "Computational Biology")
        self.assertEqual(response.data[1]["slug"], "computational-biology")

    @patch("opensearchpy.Search.execute")
    def test_score_based_sorting(self, mock_es_execute):
        """Test that results are sorted by weighted score across entity types"""
        # Arrange
        post_options = [
            {
                "_score": 2.0,  # Medium score for post
                "_source": {
                    "id": 1,
                    "title": "Test Post",
                    "created_date": "2023-01-01",
                },
            }
        ]

        hub_options = [
            {
                "_score": 1.0,  # Low score for hub
                "_source": {
                    "id": 2,
                    "name": "Test Hub",
                    "slug": "test-hub",
                    "description": "Test hub description",
                    "paper_count": 10,
                    "discussion_count": 5,
                    "created_date": "2023-01-01",
                },
            }
        ]

        user_options = [
            {
                "_score": 5.0,  # Highest base score for user
                "_source": {
                    "id": 3,
                    "full_name": "Test User",
                    "created_date": "2023-01-01",
                },
            }
        ]

        # Responses are returned in the order the indexes are queried
        mock_es_execute.side_effect = [
            _suggest_response(post_options),
            _suggest_response(hub_options),
            _suggest_response(user_options),
        ]

        # Act
        response = self.client.get(self.url + "?q=test&index=post,hub,user&limit=5")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # user (5.0 x 4.0 x 2.0 partial name match) > post (2.0 x 3.5) > hub (1.0 x 5.0)
        entity_types = [result["entity_type"] for result in response.data]
        self.assertEqual(entity_types, ["user", "post", "hub"])

    @patch("opensearchpy.Search.execute")
    def test_case_insensitive_matching(self, mock_es_execute):
        """Test that queries match regardless of case"""

        # Set up test query with mixed case
        search_query = "MiXeD cAsE"

        # Mock user result with exact match but different case
        def mock_execute_side_effect():
            class MockSuggest:
                def to_dict(self):
                    return {
                        "suggestions": [
                            {
                                "options": [
                                    {
                                        "_score": 1.0,
                                        "_source": {
                                            "id": 3,
                                            "full_name": "mixed case",
                                            # Lower case version
                                            "created_date": "2023-01-01",
                                        },
                                    }
                                ]
                            }
                        ]
                    }

            class MockResponse:
                suggest = MockSuggest()

            return MockResponse()

        mock_es_execute.side_effect = mock_execute_side_effect

        # Test with mixed case query
        response = self.client.get(f"{self.url}?q={search_query}&index=user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should get a result despite case difference
        self.assertEqual(len(response.data), 1)

        # Exact match boost should still apply (case-insensitive)
        self.assertEqual(response.data[0]["display_name"], "mixed case")
        self.assertIn("_boost", response.data[0])
        self.assertEqual(response.data[0]["_boost"], "exact_name_match")

    @patch("opensearchpy.Search.execute")
    def test_person_entity_includes_user_id(self, mock_es_execute):
        """Test that person entities from author index include user_id field"""

        user_options = [
            {
                "_score": 1.0,
                "_source": {
                    "id": 456,
                    "full_name": "Test Author",
                    "created_date": "2023-01-01",
                    "author_profile": {
                        "id": 123,
                        "profile_image": "https://example.com/image.jpg",
                        "headline": "Test Headline",
                    },
                },
            }
        ]

        class MockSuggest:
            def to_dict(self):
                return {"suggestions": [{"options": user_options}]}

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        response = self.client.get(self.url + "?q=test&index=author")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.data), 1)
        result = response.data[0]

        self.assertEqual(result["entity_type"], "person")
        self.assertIn("user_id", result)
        self.assertEqual(result["user_id"], 456)
        self.assertEqual(result["id"], 123)
        self.assertEqual(result["display_name"], "Test Author")
        self.assertEqual(result["profile_image"], "https://example.com/image.jpg")
        self.assertEqual(result["headline"], "Test Headline")
        self.assertEqual(result["created_date"], "2023-01-01")
        self.assertEqual(result["source"], "researchhub")

    @patch("opensearchpy.Search.execute")
    def test_user_and_author_indexes_are_deduplicated(self, mock_es_execute):
        """Test that index=user,author does not duplicate user search results"""

        user_options = [
            {
                "_score": 1.0,
                "_source": {
                    "id": 456,
                    "full_name": "Test Author",
                    "created_date": "2023-01-01",
                    "author_profile": {
                        "id": 123,
                        "profile_image": "https://example.com/image.jpg",
                        "headline": "Test Headline",
                    },
                },
            }
        ]

        class MockSuggest:
            def to_dict(self):
                return {"suggestions": [{"options": user_options}]}

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        response = self.client.get(self.url + "?q=test&index=user,author")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(mock_es_execute.call_count, 1)
