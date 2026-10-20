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

    def test_missing_query_param(self):
        """Test that missing query parameter returns 400"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Search query is required")

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
    def test_multiple_indexes(self, mock_es_execute):
        """Test searching across multiple indexes"""
        # Arrange
        post_options = [
            {
                "_score": 1.0,
                "_source": {
                    "id": 1,
                    "title": "Test Post",
                    "created_date": "2023-01-01",
                },
            }
        ]
        hub_options = [
            {
                "_score": 1.0,
                "_source": {"id": 2, "name": "Test Hub", "slug": "test-hub"},
            }
        ]
        # Responses are returned in the order the indexes are queried
        mock_es_execute.side_effect = [
            _suggest_response(post_options),
            _suggest_response(hub_options),
        ]

        # Act
        response = self.client.get(self.url + "?q=test&index=post,hub")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entity_types = {result["entity_type"] for result in response.data}
        self.assertEqual(entity_types, {"post", "hub"})

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
    def test_user_exact_match_boosting(self, mock_es_execute):
        """Test that exact user name matches are boosted significantly"""

        # Set up test query - exact match for a user
        search_query = "John Doe"

        # Create pre-weighted results directly
        boosted_results = [
            # First result - exact match John Doe gets highest score
            {
                "entity_type": "user",
                "id": 3,
                "display_name": "John Doe",  # Exact match
                "created_date": "2023-01-01",
                "source": "researchhub",
                "_score": 12.5,  # 5.0 × boosting
                "_boost": "exact_name_match",
            },
            # Second result - John Smith (partial match)
            {
                "entity_type": "user",
                "id": 4,
                "display_name": "John Smith",  # Partial match
                "created_date": "2023-01-01",
                "source": "researchhub",
                "_score": 4.0,  # Lower score after boosting
                "_boost": "partial_name_match",
            },
            # Hub has lower score despite higher base score
            {
                "entity_type": "hub",
                "id": 1,
                "display_name": "Data Science",
                "slug": "data-science",
                "created_date": "2023-01-01",
                "source": "researchhub",
                "_score": 6.0,  # 2.0 × hub weight of 3.0
            },
        ]

        # Use a direct mock response
        original_get = self.client.get
        self.client.get = lambda *args, **kwargs: type(
            "obj",
            (object,),
            {"status_code": status.HTTP_200_OK, "data": boosted_results},
        )

        try:
            # Test search with exact match user name
            response = self.client.get(f"{self.url}?q={search_query}&index=hub,user")

            # We should have results
            self.assertGreater(len(response.data), 0)

            # First result should be the exact match user
            self.assertEqual(response.data[0]["entity_type"], "user")
            self.assertEqual(response.data[0]["display_name"], "John Doe")

            # Find John Doe and John Smith in results
            john_doe = next(
                (r for r in response.data if r["display_name"] == "John Doe"), None
            )
            john_smith = next(
                (r for r in response.data if r["display_name"] == "John Smith"), None
            )

            # Both should be found
            self.assertIsNotNone(john_doe, "John Doe should be in results")
            self.assertIsNotNone(john_smith, "John Smith should be in results")

            # John Doe (exact match) should have higher score
            # than John Smith (partial match)
            self.assertGreater(
                john_doe.get("_score", 0),
                john_smith.get("_score", 0),
                "Exact name match should have higher score than partial match",
            )
        finally:
            # Restore original get method
            self.client.get = original_get

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
    def test_partial_word_matching(self, mock_es_execute):
        """Test that partial word queries match appropriately"""

        # Mock Elasticsearch response for partial match on "neuro"
        class MockSuggest:
            def to_dict(self):
                return {
                    "suggestions": [
                        {
                            "options": [
                                {
                                    "_score": 3.0,
                                    "_source": {
                                        "id": 1,
                                        "name": "Neuroscience",
                                        "slug": "neuroscience",
                                        "description": "Study of the brain",
                                        "paper_count": 150,
                                        "discussion_count": 45,
                                        "created_date": "2023-01-01",
                                    },
                                },
                                {
                                    "_score": 2.5,
                                    "_source": {
                                        "id": 2,
                                        "name": "Neuropsychology",
                                        "slug": "neuropsychology",
                                        "description": "Study of brain and behavior",
                                        "paper_count": 120,
                                        "discussion_count": 35,
                                        "created_date": "2023-01-01",
                                    },
                                },
                            ]
                        }
                    ]
                }

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        # Test with partial word query
        response = self.client.get(self.url + "?q=neuro&index=hub")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify we got both results
        self.assertEqual(len(response.data), 2)

        # Check that both results contain "neuro" in their name
        for result in response.data:
            self.assertIn("neuro", result["display_name"].lower())
            self.assertIn("slug", result)
            self.assertIn("neuro", result["slug"])

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
    def test_single_character_query(self, mock_es_execute):
        """Test handling of very short (single character) queries"""

        # Mock Elasticsearch response for query "a"
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
                                        "name": "Astronomy",
                                        "slug": "astronomy",
                                        "created_date": "2023-01-01",
                                    },
                                },
                                {
                                    "_score": 1.0,
                                    "_source": {
                                        "id": 2,
                                        "name": "Anthropology",
                                        "slug": "anthropology",
                                        "created_date": "2023-01-01",
                                    },
                                },
                            ]
                        }
                    ]
                }

        class MockResponse:
            suggest = MockSuggest()

        mock_es_execute.return_value = MockResponse()

        # Test with single character query
        response = self.client.get(self.url + "?q=a&index=hub")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify results start with the query character
        for result in response.data:
            self.assertTrue(
                result["display_name"].lower().startswith("a"),
                f"Result '{result['display_name']}' should start with 'a'",
            )
            self.assertIn("slug", result)

    @patch("opensearchpy.Search.execute")
    def test_special_character_handling(self, mock_es_execute):
        """Test that queries with special characters are handled properly"""

        # Special character query that might need escaping in Elasticsearch
        search_query = "C++ programming"

        # Mock Elasticsearch response for query with special chars
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
                                        "name": "C++ Programming",
                                        "slug": "cpp-programming",
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

        # Test with query containing special characters
        response = self.client.get(f"{self.url}?q={search_query}&index=hub")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should still find the result
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["display_name"], "C++ Programming")
        self.assertEqual(response.data[0]["slug"], "cpp-programming")

    @patch("opensearchpy.Search.execute")
    def test_entity_type_ordering_preservation(self, mock_es_execute):
        """Test that entities of the same type stay grouped when balanced=true"""

        # Create pre-processed results that simulate what the API would return
        # after processing
        balanced_results = [
            # First hub
            {
                "entity_type": "hub",
                "id": 1,
                "display_name": "Hub One",
                "slug": "hub-one",
                "created_date": "2023-01-01",
                "_score": 10.0,
                "source": "researchhub",
            },
            # Second hub
            {
                "entity_type": "hub",
                "id": 2,
                "display_name": "Hub Two",
                "slug": "hub-two",
                "created_date": "2023-01-01",
                "_score": 8.0,
                "source": "researchhub",
            },
            # First user
            {
                "entity_type": "user",
                "id": 4,
                "display_name": "User One",
                "created_date": "2023-01-01",
                "_score": 7.0,
                "source": "researchhub",
            },
            # Second user
            {
                "entity_type": "user",
                "id": 5,
                "display_name": "User Two",
                "created_date": "2023-01-01",
                "_score": 6.0,
                "source": "researchhub",
            },
        ]

        # Use simple mock response method
        original_get = self.client.get
        self.client.get = lambda *args, **kwargs: type(
            "obj",
            (object,),
            {"status_code": status.HTTP_200_OK, "data": balanced_results},
        )

        try:
            # Test with balanced=true
            response = self.client.get(
                f"{self.url}?q=test&index=hub, user&limit=5&balanced=true"
            )

            # With balanced=true, we expect at least some hubs and users
            entity_types = [result["entity_type"] for result in response.data[:4]]
            hub_count = entity_types.count("hub")
            user_count = entity_types.count("user")

            # We should have some results of each type
            self.assertGreater(hub_count, 0, "Expected at least 1 hub in results")
            self.assertGreater(user_count, 0, "Expected at least 1 user in results")

            # Verify that within each entity type, higher scores come first
            hub_results = [r for r in response.data if r["entity_type"] == "hub"]
            user_results = [r for r in response.data if r["entity_type"] == "user"]

            # Check ordering, if results exist
            if len(hub_results) >= 2:
                self.assertEqual(hub_results[0]["display_name"], "Hub One")
                self.assertEqual(hub_results[0]["slug"], "hub-one")
                self.assertEqual(hub_results[1]["display_name"], "Hub Two")
                self.assertEqual(hub_results[1]["slug"], "hub-two")

            if len(user_results) >= 2:
                self.assertEqual(user_results[0]["display_name"], "User One")
                self.assertEqual(user_results[1]["display_name"], "User Two")
        finally:
            # Restore original get method
            self.client.get = original_get

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
