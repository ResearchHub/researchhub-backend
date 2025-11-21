from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from paper.ingestion.clients.enrichment.github import GithubClient, GithubMetricsClient


class TestGithubClient(TestCase):

    def setUp(self):
        self.client = GithubClient(api_token="test_token")

    @patch("paper.ingestion.clients.enrichment.github.requests.get")
    @patch("paper.ingestion.clients.enrichment.github.RateLimiter.wait_if_needed")
    def test_search_success(self, mock_rate_limiter, mock_get):
        """
        Test successful search.
        """
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total_count": 42,
        }
        mock_get.return_value = mock_response

        # Act
        result = self.client.search("issues", "test query")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual(result["total_count"], 42)
        mock_rate_limiter.assert_called_once()
        mock_get.assert_called_once_with(
            "https://api.github.com/search/issues",
            headers=self.client.headers,
            params={"q": "test query", "per_page": 1},
            timeout=10,
        )

    @patch("paper.ingestion.clients.enrichment.github.requests.get")
    @patch("paper.ingestion.clients.enrichment.github.RateLimiter.wait_if_needed")
    def test_search_authentication_required(self, mock_rate_limiter, mock_get):
        """
        Test search with authentication required (401).
        """
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            response=mock_response
        )
        mock_get.return_value = mock_response

        # Act & Assert
        with self.assertRaises(requests.HTTPError):
            self.client.search("code", "test query")

    @patch("paper.ingestion.clients.enrichment.github.requests.get")
    @patch("paper.ingestion.clients.enrichment.github.RateLimiter.wait_if_needed")
    def test_search_rate_limit_exceeded(self, mock_rate_limiter, mock_get):
        """
        Test search with rate limit exceeded (403).
        """
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            response=mock_response
        )
        mock_get.return_value = mock_response

        # Act & Assert
        with self.assertRaises(requests.HTTPError):
            self.client.search("issues", "test query")

    @patch("paper.ingestion.clients.enrichment.github.requests.get")
    @patch("paper.ingestion.clients.enrichment.github.RateLimiter.wait_if_needed")
    def test_search_timeout(self, mock_rate_limiter, mock_get):
        """
        Test search with timeout.
        """
        # Arrange
        mock_get.side_effect = requests.Timeout("Request timed out")

        # Act & Assert
        with self.assertRaises(requests.Timeout):
            self.client.search("issues", "test query")

    @patch("paper.ingestion.clients.enrichment.github.requests.get")
    @patch("paper.ingestion.clients.enrichment.github.RateLimiter.wait_if_needed")
    def test_search_request_exception(self, mock_rate_limiter, mock_get):
        """
        Test search with generic request exception.
        """
        # Arrange
        mock_get.side_effect = requests.RequestException("Network error")

        # Act & Assert
        with self.assertRaises(requests.RequestException):
            self.client.search("issues", "test query")

    def test_client_with_token(self):
        """
        Test client initialization with API token.
        """
        # Act
        client = GithubClient(api_token="my_token")

        # Assert
        self.assertEqual(client.api_token, "my_token")
        self.assertEqual(client.headers["Authorization"], "Bearer my_token")


class TestGithubMetricsClient(TestCase):

    def setUp(self):
        self.mock_github_client = Mock(spec=GithubClient)
        self.client = GithubMetricsClient(github_client=self.mock_github_client)

    def test_get_mentions(self):
        """
        Test getting mentions successfully.
        """
        # Arrange
        self.mock_github_client.search.side_effect = [
            {"total_count": 5, "items": []},  # issues
            {"total_count": 3, "items": []},  # commits
            {"total_count": 2, "items": []},  # repositories
        ]

        # Act
        result = self.client.get_mentions("10.1234/test")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual(result["total_mentions"], 10)
        self.assertEqual(result["term"], "10.1234/test")
        self.assertEqual(result["breakdown"]["issues"], 5)
        self.assertEqual(result["breakdown"]["commits"], 3)
        self.assertEqual(result["breakdown"]["repositories"], 2)

    def test_get_mentions_no_results(self):
        """
        Test getting mentions when no results found.
        """
        # Arrange
        self.mock_github_client.search.return_value = {"total_count": 0, "items": []}

        # Act
        result = self.client.get_mentions("10.1234/notfound")

        # Assert - Should return valid response with 0 counts
        assert result is not None
        self.assertEqual(result["total_mentions"], 0)
        self.assertEqual(result["term"], "10.1234/notfound")
        self.assertEqual(result["breakdown"]["issues"], 0)
        self.assertEqual(result["breakdown"]["commits"], 0)
        self.assertEqual(result["breakdown"]["repositories"], 0)

    def test_get_mentions_partial_failure(self):
        """
        Test getting mentions with partial search failures.
        """
        # Arrange
        self.mock_github_client.search.side_effect = [
            {"total_count": 5, "items": []},  # issues - success
            None,  # commits - failure
            {"total_count": 2, "items": []},  # repositories - success
        ]

        # Act
        result = self.client.get_mentions("10.1234/test")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual(result["total_mentions"], 7)
        self.assertEqual(len(result["breakdown"]), 2)  # Only 2 successful searches
        self.assertIn("issues", result["breakdown"])
        self.assertIn("repositories", result["breakdown"])
        self.assertNotIn("commits", result["breakdown"])

    def test_get_mentions_all_failures(self):
        """
        Test getting mentions when all searches fail.
        """
        # Arrange
        self.mock_github_client.search.return_value = None

        # Act
        result = self.client.get_mentions("10.1234/test")

        # Assert
        self.assertIsNone(result)

    def test_search_area_invalid_area(self):
        """
        Test searching with invalid area raises ValueError.
        """
        # Act & Assert
        with self.assertRaises(ValueError) as context:
            self.client._search_area("10.1234/test", "invalid_area")

        self.assertIn("Invalid search area", str(context.exception))

    def test_search_area_valid_areas(self):
        """
        Test that all valid search areas are accepted.
        """
        # Arrange
        self.mock_github_client.search.return_value = {"total_count": 1, "items": []}

        # Act & Assert
        for area in GithubMetricsClient.VALID_SEARCH_AREAS:
            result = self.client._search_area("10.1234/test", area)
            self.assertEqual(result, 1)

    def test_search_area_zero_results(self):
        """
        Test searching area with zero results.
        """
        # Arrange
        self.mock_github_client.search.return_value = {"total_count": 0, "items": []}

        # Act
        result = self.client._search_area("10.1234/test", "issues")

        # Assert
        self.assertEqual(result, 0)

    def test_valid_search_areas(self):
        """
        Test that valid search areas include all options.
        """
        # Assert
        self.assertEqual(
            GithubMetricsClient.VALID_SEARCH_AREAS,
            ["code", "issues", "commits", "repositories"],
        )
