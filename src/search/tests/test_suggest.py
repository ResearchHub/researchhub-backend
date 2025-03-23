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

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_hub_index_search(self, mock_es_execute, mock_openalex):
        """Test searching in the hub index"""
        # Mock empty OpenAlex response since we're not using it for hub index
        mock_openalex.return_value = {"results": []}

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
                        "Computational biology involves the development and application "
                        "of data-analytical methods."
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

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_balanced_results(self, mock_es_execute, mock_openalex):
        """Test that balanced results include various entity types"""
        # Mock OpenAlex response with papers
        paper_openalex_results = []
        for i in range(5):
            paper_openalex_results.append(
                {
                    "external_id": f"10.1234/test.{i}",
                    "display_name": f"Test Paper {i}",
                    "hint": f"Author {i}",
                    "cited_by_count": i,
                    "id": f"W{i}",
                }
            )
        mock_openalex.return_value = {"results": paper_openalex_results}

        # Mock Elasticsearch response with different types
        def mock_execute_side_effect():
            class MockSuggest:
                def to_dict(self):
                    if "paper" in mock_es_execute.call_args[0][0].index:
                        return {"suggestions": []}  # Use OpenAlex results for papers
                    elif "hub" in mock_es_execute.call_args[0][0].index:
                        return {
                            "suggestions": [
                                {
                                    "options": [
                                        {
                                            "_score": 10.0,  # High score for hubs
                                            "_source": {
                                                "id": 1,
                                                "name": "Computer Science",
                                                "slug": "computer-science",
                                                "description": "Computer science description",
                                                "paper_count": 150,
                                                "discussion_count": 45,
                                            },
                                        },
                                        {
                                            "_score": 9.0,
                                            "_source": {
                                                "id": 2,
                                                "name": "Biology",
                                                "slug": "biology",
                                                "description": "Biology description",
                                                "paper_count": 120,
                                                "discussion_count": 35,
                                            },
                                        },
                                    ]
                                }
                            ]
                        }
                    elif "user" in mock_es_execute.call_args[0][0].index:
                        return {
                            "suggestions": [
                                {
                                    "options": [
                                        {
                                            "_score": 5.0,
                                            "_source": {
                                                "id": 3,
                                                "full_name": "John Doe",
                                            },
                                        },
                                        {
                                            "_score": 4.0,
                                            "_source": {
                                                "id": 4,
                                                "full_name": "Jane Smith",
                                            },
                                        },
                                    ]
                                }
                            ]
                        }
                    return {"suggestions": []}  # Default empty response

            class MockResponse:
                suggest = MockSuggest()

            return MockResponse()

        mock_es_execute.side_effect = mock_execute_side_effect

        # Test without balanced results (should prioritize higher scores)
        response = self.client.get(self.url + "?q=test&index=paper,hub,user&limit=6")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # In non-balanced mode, we expect mostly hubs (highest scores)
        entity_counts = {}
        for result in response.data:
            entity_type = result.get("entity_type")
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1

        # Likely dominated by highest scoring type
        self.assertTrue(
            max(entity_counts.values()) > 2,
            "Expected one entity type to dominate in non-balanced mode",
        )

        # Test with balanced results
        response = self.client.get(
            self.url + "?q=test&index=paper,hub,user&limit=6&balanced=true"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that we have results from all entity types
        entity_types = set(result.get("entity_type") for result in response.data)
        self.assertEqual(
            len(entity_types), 3, "Expected results from all three entity types"
        )

        # Check minimum representation
        entity_counts = {}
        for result in response.data:
            entity_type = result.get("entity_type")
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1

        # Each entity type should have at least 1 result
        for entity_type in ["paper", "hub", "user"]:
            self.assertGreaterEqual(
                entity_counts.get(entity_type, 0),
                1,
                f"Expected at least 1 result for {entity_type}",
            )

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_weighted_scoring_with_default_weights(
        self, mock_es_execute, mock_openalex
    ):
        """Test that default entity type weights properly prioritize results"""
        # Mock OpenAlex response with papers
        paper_openalex_results = []
        for i in range(3):
            paper_openalex_results.append(
                {
                    "external_id": f"10.1234/test.{i}",
                    "display_name": f"Test Paper {i}",
                    "hint": f"Author {i}",
                    "cited_by_count": i,
                    "id": f"W{i}",
                }
            )
        mock_openalex.return_value = {"results": paper_openalex_results}

        # Mock Elasticsearch response with different types (all with equal scores)
        def mock_execute_side_effect():
            class MockSuggest:
                def to_dict(self):
                    if "paper" in mock_es_execute.call_args[0][0].index:
                        return {"suggestions": []}  # Use OpenAlex results for papers
                    elif "hub" in mock_es_execute.call_args[0][0].index:
                        return {
                            "suggestions": [
                                {
                                    "options": [
                                        {
                                            "_score": 1.0,
                                            "_source": {
                                                "id": 1,
                                                "name": "Computer Science",
                                                "slug": "computer-science",
                                                "description": "CS description",
                                                "paper_count": 150,
                                                "discussion_count": 45,
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    elif "user" in mock_es_execute.call_args[0][0].index:
                        return {
                            "suggestions": [
                                {
                                    "options": [
                                        {
                                            "_score": 1.0,
                                            "_source": {
                                                "id": 3,
                                                "full_name": "John Doe",
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    elif "post" in mock_es_execute.call_args[0][0].index:
                        return {
                            "suggestions": [
                                {
                                    "options": [
                                        {
                                            "_score": 1.0,
                                            "_source": {
                                                "id": 5,
                                                "title": "Sample Post",
                                                "authors": [
                                                    {"full_name": "Author Name"}
                                                ],
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    return {"suggestions": []}  # Default empty response

            class MockResponse:
                suggest = MockSuggest()

            return MockResponse()

        mock_es_execute.side_effect = mock_execute_side_effect

        # Test with default weights
        response = self.client.get(
            self.url + "?q=test&index=paper,hub,user,post&limit=5"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify order based on default weights (hubs first, then papers, then users/authors, then posts)
        entity_types = [result["entity_type"] for result in response.data[:4]]

        # Since all mock scores are equal, entity order should be determined by default weights
        # (first should be hub, somewhere in the middle should be paper, last should be post)
        self.assertEqual(
            entity_types[0], "hub", "Hub should be first with highest default weight"
        )
        self.assertIn("paper", entity_types, "Paper should be included in results")

        # Find positions of each type
        try:
            hub_position = entity_types.index("hub")
            paper_position = entity_types.index("paper")
            post_position = entity_types.index("post")

            # Verify descending order of weights: hub > paper > post
            self.assertLess(
                hub_position, paper_position, "Hubs should be prioritized over papers"
            )
            self.assertLess(
                paper_position, post_position, "Papers should be prioritized over posts"
            )
        except ValueError:
            # If some types aren't found, the test will fail with a clearer message
            self.fail(
                f"Expected entity types not found in results. Got: {entity_types}"
            )

    @patch("utils.openalex.OpenAlex.autocomplete_works")
    @patch("elasticsearch_dsl.Search.execute")
    def test_user_exact_match_boosting(self, mock_es_execute, mock_openalex):
        """Test that exact user name matches are boosted significantly"""
        # Mock OpenAlex response (for papers)
        mock_openalex.return_value = {"results": []}

        # Set up test query - exact match for a user
        search_query = "John Doe"

        # Mock Elasticsearch response with users and hubs (normally hubs would rank higher)
        def mock_execute_side_effect():
            class MockSuggest:
                def to_dict(self):
                    if "hub" in mock_es_execute.call_args[0][0].index:
                        return {
                            "suggestions": [
                                {
                                    "options": [
                                        {
                                            "_score": 2.0,  # Higher base score for hub
                                            "_source": {
                                                "id": 1,
                                                "name": "Data Science",
                                                "slug": "data-science",
                                                "description": "Data science",
                                                "paper_count": 100,
                                                "discussion_count": 20,
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    elif "user" in mock_es_execute.call_args[0][0].index:
                        return {
                            "suggestions": [
                                {
                                    "options": [
                                        {
                                            "_score": 1.0,  # Lower base score for user
                                            "_source": {
                                                "id": 3,
                                                "full_name": "John Doe",  # Exact match
                                            },
                                        },
                                        {
                                            "_score": 0.8,
                                            "_source": {
                                                "id": 4,
                                                "full_name": "John Smith",  # Partial match
                                            },
                                        },
                                    ]
                                }
                            ]
                        }
                    return {"suggestions": []}

            class MockResponse:
                suggest = MockSuggest()

            return MockResponse()

        mock_es_execute.side_effect = mock_execute_side_effect

        # Test search with our exact match user name
        response = self.client.get(f"{self.url}?q={search_query}&index=hub,user")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # We should have at least 2 results
        self.assertGreaterEqual(len(response.data), 2)

        # Find positions of each entity type
        results_by_id = {result.get("id"): result for result in response.data}

        # First result should be the exact match user despite hub having higher base score
        self.assertEqual(response.data[0]["entity_type"], "user")
        self.assertEqual(response.data[0]["display_name"], "John Doe")

        # Find John Doe and John Smith in results
        john_doe = next(
            (r for r in response.data if r.get("display_name") == "John Doe"), None
        )
        john_smith = next(
            (r for r in response.data if r.get("display_name") == "John Smith"), None
        )

        # Both should be found
        self.assertIsNotNone(john_doe, "John Doe should be in results")
        self.assertIsNotNone(john_smith, "John Smith should be in results")

        # John Doe (exact match) should have higher score than John Smith (partial match)
        self.assertGreater(
            john_doe.get("_score", 0),
            john_smith.get("_score", 0),
            "Exact name match should have higher score than partial match",
        )
