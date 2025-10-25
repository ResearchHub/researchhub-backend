import json
import os
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from paper.ingestion.clients.openalex import OpenAlexClient, OpenAlexConfig
from paper.ingestion.exceptions import FetchError, TimeoutError


class TestOpenAlexClient(TestCase):
    """
    Test cases for the OpenAlex client.
    """

    def setUp(self):
        self.config = OpenAlexConfig(email="test@example.com")
        self.client = OpenAlexClient(self.config)

        # Load fixture files
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")

        with open(
            os.path.join(fixtures_dir, "openalex_sample_response.json"), "r"
        ) as f:
            self.sample_list_response = json.load(f)

        with open(
            os.path.join(fixtures_dir, "openalex_sample_get_by_doi_response.json"),
            "r",
        ) as f:
            self.sample_single_response = json.load(f)

        with open(os.path.join(fixtures_dir, "openalex_empty_response.json"), "r") as f:
            self.empty_list_response = json.load(f)

    def test_config_defaults(self):
        """
        Test OpenAlex config has correct defaults.
        """
        # Arrange & Act
        config = OpenAlexConfig()

        # Assert
        self.assertEqual(config.source_name, "openalex")
        self.assertEqual(config.base_url, "https://api.openalex.org")
        self.assertEqual(config.rate_limit, 10.0)  # 10 requests per second
        self.assertEqual(config.page_size, 200)  # OpenAlex max
        self.assertEqual(config.request_timeout, 30.0)
        self.assertEqual(config.max_results_per_query, 200)

    def test_config_with_email(self):
        """
        Test OpenAlex config with email for polite pool.
        """
        # Arrange
        config = OpenAlexConfig(email="test@example.com")

        # Act
        client = OpenAlexClient(config)

        # Assert
        self.assertEqual(client.headers["User-Agent"], "mailto:test@example.com")

    def test_config_with_api_key(self):
        """
        Test OpenAlex config with API key.
        """
        # Arrange
        config = OpenAlexConfig(api_key="test-api-key-123")

        # Act
        client = OpenAlexClient(config)

        # Assert
        self.assertEqual(client.api_key, "test-api-key-123")
        # API key should not be in headers
        self.assertNotIn("Authorization", client.headers)

    def test_fetch_includes_api_key_in_params(self):
        """
        Test that fetch method includes API key in query parameters.
        """
        # Arrange
        config = OpenAlexConfig(api_key="test-api-key-123", email="test@example.com")
        client = OpenAlexClient(config)

        with patch("requests.Session.get") as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = self.sample_list_response
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            # Act
            client.fetch("/works", {"filter": "is_oa:true"})

            # Assert
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            params = call_args[1]["params"]
            self.assertEqual(params["api_key"], "test-api-key-123")
            self.assertEqual(params["filter"], "is_oa:true")

    def test_parse_list_response(self):
        """
        Test parsing of OpenAlex list response.
        """
        # Act
        papers = self.client.parse(self.sample_list_response)

        # Assert
        # Should have 3 papers from the fixture
        self.assertEqual(len(papers), 3)

        # Check first paper structure
        paper1 = papers[0]
        self.assertIn("raw_data", paper1)
        self.assertEqual(paper1["source"], "openalex")

        # Verify the raw data contains expected fields
        raw = paper1["raw_data"]
        self.assertEqual(raw["id"], "https://openalex.org/W3001118548")
        self.assertEqual(raw["doi"], "https://doi.org/10.1016/s0140-6736(20)30183-5")
        self.assertIn("Clinical features", raw["title"])
        self.assertEqual(raw["publication_year"], 2020)

    def test_parse_empty_response(self):
        """
        Test parsing empty response.
        """
        # Act
        papers = self.client.parse(self.empty_list_response)

        # Assert
        self.assertEqual(papers, [])

    def test_parse_missing_results_key(self):
        """
        Test parsing response without results key.
        """
        # Arrange
        invalid_response = {"meta": {"count": 0}}

        # Act
        papers = self.client.parse(invalid_response)

        # Assert
        self.assertEqual(papers, [])

    def test_parse_non_dict_response(self):
        """
        Test parsing non-dict response returns empty list.
        """
        # Act & Assert
        papers = self.client.parse("Invalid response")
        self.assertEqual(papers, [])

        papers = self.client.parse(None)
        self.assertEqual(papers, [])

        papers = self.client.parse([])
        self.assertEqual(papers, [])

    @patch("requests.Session.get")
    def test_fetch(self, mock_get):
        """
        Test basic fetch method.
        """
        # Arrange
        mock_response = MagicMock()
        mock_response.json.return_value = self.sample_list_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Act
        result = self.client.fetch("/works", {"filter": "is_oa:true"})

        # Assert
        self.assertEqual(result, self.sample_list_response)
        mock_get.assert_called_once_with(
            "https://api.openalex.org/works",
            params={"filter": "is_oa:true"},
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "User-Agent": "mailto:test@example.com",
            },
        )

    @patch("requests.Session.get")
    def test_fetch_timeout(self, mock_get):
        """
        Test fetch with timeout.
        """
        # Arrange
        mock_get.side_effect = requests.Timeout("Request timed out")

        # Act & Assert
        with self.assertRaises(TimeoutError) as context:
            self.client.fetch("/works")

        self.assertIn("Request timed out after 30.0s", str(context.exception))

    @patch("requests.Session.get")
    def test_fetch_request_error(self, mock_get):
        """
        Test fetch with request error.
        """
        # Arrange
        mock_get.side_effect = requests.RequestException("Connection error")

        # Act & Assert
        with self.assertRaises(FetchError) as context:
            self.client.fetch("/works")

        self.assertIn("Failed to fetch from", str(context.exception))
        self.assertIn("Connection error", str(context.exception))

    @patch.object(OpenAlexClient, "fetch_with_retry")
    @patch.object(OpenAlexClient, "process_page")
    def test_fetch_recent_basic(self, mock_process, mock_fetch):
        """
        Test fetching recent papers.
        """
        # Arrange
        mock_fetch.return_value = self.sample_list_response
        mock_process.return_value = self.client.parse(self.sample_list_response)

        # Act
        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1),
            until=datetime(2025, 1, 7),
            max_results=10,
        )

        # Assert
        self.assertEqual(len(papers), 3)
        self.assertIn("raw_data", papers[0])

        # Verify query was constructed correctly
        call_args = mock_fetch.call_args
        params = call_args[0][1]  # Get params from call
        self.assertIn("from_publication_date:2025-01-01", params["filter"])
        self.assertIn("to_publication_date:2025-01-07", params["filter"])
        self.assertEqual(params["sort"], "publication_date:desc")

    @patch.object(OpenAlexClient, "fetch_with_retry")
    @patch.object(OpenAlexClient, "process_page")
    def test_fetch_recent_default_dates(self, mock_process, mock_fetch):
        """
        Test fetch_recent with default date range.
        """
        # Arrange
        mock_fetch.return_value = self.empty_list_response
        mock_process.return_value = []

        # Act
        self.client.fetch_recent()

        # Assert
        # Should use default 7 day range
        call_args = mock_fetch.call_args
        params = call_args[0][1]
        filter_str = params["filter"]

        # Check that date filter is present
        self.assertIn("from_publication_date:", filter_str)
        self.assertIn("to_publication_date:", filter_str)

    @patch.object(OpenAlexClient, "fetch_with_retry")
    @patch.object(OpenAlexClient, "process_page")
    def test_fetch_recent_pagination(self, mock_process, mock_fetch):
        """
        Test pagination handling in fetch_recent.
        """
        # Arrange
        first_page = {
            "meta": {"next_cursor": "cursor_page2", "count": 250},
            "results": [{"id": f"W{i}"} for i in range(200)],
        }
        second_page = {
            "meta": {"next_cursor": None, "count": 250},
            "results": [{"id": f"W{i}"} for i in range(200, 250)],
        }

        mock_fetch.side_effect = [first_page, second_page]
        mock_process.side_effect = [
            self.client.parse(first_page),
            self.client.parse(second_page),
        ]

        # Act
        papers = self.client.fetch_recent(
            since=datetime(2025, 1, 1), until=datetime(2025, 1, 2)
        )

        # Assert
        # Should have fetched all papers
        self.assertEqual(len(papers), 250)
        self.assertEqual(mock_fetch.call_count, 2)

        # Check cursor progression
        first_call_params = mock_fetch.call_args_list[0][0][1]
        second_call_params = mock_fetch.call_args_list[1][0][1]
        self.assertEqual(first_call_params["cursor"], "*")
        self.assertEqual(second_call_params["cursor"], "cursor_page2")

    @patch.object(OpenAlexClient, "fetch_with_retry")
    def test_fetch_by_doi(self, mock_fetch):
        """
        Test fetching a single paper by DOI.
        """
        # Arrange
        mock_fetch.return_value = self.sample_single_response

        # Act
        paper = self.client.fetch_by_doi("10.7717/peerj.4375")
        # Assert
        self.assertIsNotNone(paper)
        self.assertEqual(paper["source"], "openalex")
        self.assertEqual(paper["raw_data"]["id"], "https://openalex.org/W2741809807")

        # Verify correct URL was called
        mock_fetch.assert_called_with("/works/https://doi.org/10.7717/peerj.4375")

    @patch.object(OpenAlexClient, "fetch_with_retry")
    def test_fetch_by_doi_with_url_prefix(self, mock_fetch):
        """
        Test fetching by DOI with URL prefix.
        """
        # Arrange
        mock_fetch.return_value = self.sample_single_response

        # Act - Test with https prefix
        paper = self.client.fetch_by_doi("https://doi.org/10.7717/peerj.4375")
        # Assert
        self.assertIsNotNone(paper)

        # Should have cleaned the DOI
        mock_fetch.assert_called_with("/works/https://doi.org/10.7717/peerj.4375")

        # Act - Test with http prefix
        mock_fetch.reset_mock()
        paper = self.client.fetch_by_doi("http://doi.org/10.7717/peerj.4375")
        # Assert
        self.assertIsNotNone(paper)

        mock_fetch.assert_called_with("/works/https://doi.org/10.7717/peerj.4375")

    @patch.object(OpenAlexClient, "fetch_with_retry")
    def test_fetch_by_doi_not_found(self, mock_fetch):
        """
        Test fetching by DOI when paper not found.
        """
        # Arrange
        mock_fetch.side_effect = FetchError("404 Not Found")

        # Act
        paper = self.client.fetch_by_doi("10.1234/nonexistent")

        # Assert
        self.assertIsNone(paper)

    @patch.object(OpenAlexClient, "fetch_with_retry")
    @patch.object(OpenAlexClient, "process_page")
    def test_fetch_by_ids_dois(self, mock_process, mock_fetch):
        """
        Test fetching papers by multiple DOIs.
        """
        # Arrange
        mock_fetch.return_value = self.sample_list_response
        mock_process.return_value = self.client.parse(self.sample_list_response)
        dois = ["10.1234/test1", "10.5678/test2"]

        # Act
        papers = self.client.fetch_by_ids(dois, id_type="doi")

        # Assert
        self.assertEqual(len(papers), 3)  # Based on sample response

        # Verify filter was constructed correctly
        call_args = mock_fetch.call_args
        params = call_args[0][1]
        expected_filter = (
            "doi:https://doi.org/10.1234/test1|https://doi.org/10.5678/test2"
        )
        self.assertEqual(params["filter"], expected_filter)

    @patch.object(OpenAlexClient, "fetch_with_retry")
    @patch.object(OpenAlexClient, "process_page")
    def test_fetch_by_ids_dois_with_prefixes(self, mock_process, mock_fetch):
        """
        Test fetching by DOIs that already have URL prefixes.
        """
        # Arrange
        mock_fetch.return_value = self.sample_list_response
        mock_process.return_value = self.client.parse(self.sample_list_response)
        dois = [
            "https://doi.org/10.1234/test1",
            "http://doi.org/10.5678/test2",
            "10.9999/test3",  # Mix of prefixed and non-prefixed
        ]

        # Act
        self.client.fetch_by_ids(dois, id_type="doi")

        # Assert
        # Verify DOIs were cleaned before constructing filter
        call_args = mock_fetch.call_args
        params = call_args[0][1]
        expected_filter = (
            "doi:https://doi.org/10.1234/test1|"
            "https://doi.org/10.5678/test2|"
            "https://doi.org/10.9999/test3"
        )
        self.assertEqual(params["filter"], expected_filter)

    @patch.object(OpenAlexClient, "fetch_with_retry")
    @patch.object(OpenAlexClient, "process_page")
    def test_fetch_by_ids_openalex(self, mock_process, mock_fetch):
        """
        Test fetching by OpenAlex IDs.
        """
        # Arrange
        mock_fetch.return_value = self.sample_list_response
        mock_process.return_value = self.client.parse(self.sample_list_response)
        ids = ["W2741809807", "W3001118548"]

        # Act
        self.client.fetch_by_ids(ids, id_type="openalex")

        # Assert
        call_args = mock_fetch.call_args
        params = call_args[0][1]
        self.assertEqual(params["filter"], "openalex:W2741809807|W3001118548")

    def test_fetch_by_ids_empty_list(self):
        """
        Test fetch_by_ids with empty list.
        """
        # Act
        papers = self.client.fetch_by_ids([])

        # Assert
        self.assertEqual(papers, [])

    def test_fetch_by_ids_unsupported_type(self):
        """
        Test fetch_by_ids with unsupported ID type.
        """
        # Act
        papers = self.client.fetch_by_ids(["123"], id_type="unsupported")

        # Assert
        self.assertEqual(papers, [])

    @patch.object(OpenAlexClient, "fetch_with_retry")
    def test_fetch_by_ids_error_handling(self, mock_fetch):
        """
        Test error handling in fetch_by_ids.
        """
        # Arrange
        mock_fetch.side_effect = Exception("API error")

        # Act
        papers = self.client.fetch_by_ids(["10.1234/test"], id_type="doi")

        # Assert
        self.assertEqual(papers, [])

    @patch.object(OpenAlexClient, "fetch_with_retry")
    def test_fetch_recent_with_additional_filters(self, mock_fetch):
        """
        Test fetch_recent with additional filters.
        """
        # Arrange
        mock_fetch.return_value = self.empty_list_response
        filters = {
            "is_oa": "true",
            "has_doi": "true",
            "type": "article",
        }

        # Act
        self.client.fetch_recent(
            since=datetime(2025, 1, 1),
            until=datetime(2025, 1, 7),
            filters=filters,
        )

        # Assert
        call_args = mock_fetch.call_args
        params = call_args[0][1]
        filter_str = params["filter"]

        self.assertIn("from_publication_date:2025-01-01", filter_str)
        self.assertIn("to_publication_date:2025-01-07", filter_str)
        self.assertIn("is_oa:true", filter_str)
        self.assertIn("has_doi:true", filter_str)
        self.assertIn("type:article", filter_str)

    @patch.object(OpenAlexClient, "fetch_with_retry")
    def test_fetch_recent_max_results_limit(self, mock_fetch):
        """
        Test that fetch_recent respects max_results limit.
        """
        # Arrange
        large_response = {
            "meta": {"next_cursor": "next", "count": 500},
            "results": [{"id": f"W{i}"} for i in range(200)],
        }
        mock_fetch.return_value = large_response

        # Act
        self.client.fetch_recent(
            since=datetime(2025, 1, 1),
            until=datetime(2025, 1, 7),
            max_results=50,
        )

        # Assert
        # Should stop at max_results even if more are available
        call_args = mock_fetch.call_args
        params = call_args[0][1]
        self.assertEqual(params["per-page"], 50)  # Should request only what's needed

    def test_rate_limiter(self):
        """
        Test that rate limiter enforces delays between requests.
        """
        # Arrange
        with patch("time.sleep") as mock_sleep:
            with patch.object(self.client, "fetch") as mock_fetch:
                mock_fetch.return_value = self.sample_list_response

                # Act
                self.client.fetch_with_rate_limit("/works")
                self.client.fetch_with_rate_limit("/works")

                # Assert
                # Should have slept to respect rate limit
                # (10 requests/second = 0.1s delay)
                mock_sleep.assert_called()
