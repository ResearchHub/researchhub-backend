from unittest import TestCase
from unittest.mock import Mock, patch

from paper.ingestion.clients.altmetric import AltmetricClient


class TestAltmetricClient(TestCase):
    """Test suite for the AltmetricClient."""

    def setUp(self):
        """Set up test client."""
        self.client = AltmetricClient()

    def test_clean_doi_with_http_prefix(self):
        """Test DOI cleaning with HTTP prefixes."""
        test_cases = [
            ("https://doi.org/10.1038/nature12373", "10.1038/nature12373"),
            ("http://dx.doi.org/10.1038/nature12373", "10.1038/nature12373"),
            ("doi:10.1038/nature12373", "10.1038/nature12373"),
            ("DOI:10.1038/nature12373", "10.1038/nature12373"),
            ("10.1038/nature12373", "10.1038/nature12373"),
        ]

        for input_doi, expected in test_cases:
            self.assertEqual(self.client._clean_doi(input_doi), expected)

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_doi_success(self, mock_session):
        """Test successful DOI fetch."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "score": 35.25,
            "doi": "10.1038/nature12373",
            "altmetric_id": 1234567,
        }

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.client.fetch_by_doi("10.1038/nature12373")

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["score"], 35.25)
        self.assertEqual(result["doi"], "10.1038/nature12373")

        # Verify the correct URL was called
        mock_session_instance.get.assert_called_once_with(
            "https://api.altmetric.com/v1/doi/10.1038/nature12373",
            headers=self.client.headers,
            timeout=self.client.timeout,
        )

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_doi_not_found(self, mock_session):
        """Test DOI fetch when paper is not found in Altmetric."""
        mock_response = Mock()
        mock_response.status_code = 404

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.client.fetch_by_doi("10.1038/nonexistent")

        self.assertIsNone(result)

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_doi_rate_limited(self, mock_session):
        """Test DOI fetch when rate limited."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = Exception("Rate limited")

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.client.fetch_by_doi("10.1038/nature12373")

        self.assertIsNone(result)
        mock_response.raise_for_status.assert_called_once()

    def test_fetch_empty_doi(self):
        """Test fetch with empty DOI."""
        result = self.client.fetch_by_doi("")
        self.assertIsNone(result)

        result = self.client.fetch_by_doi(None)
        self.assertIsNone(result)

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_network_error(self, mock_session):
        """Test fetch with network error."""
        mock_session_instance = Mock()
        mock_session_instance.get.side_effect = Exception("Network error")
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.client.fetch_by_doi("10.1038/nature12373")
        self.assertIsNone(result)

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_arxiv_id_success(self, mock_session):
        """
        Test successful arXiv ID fetch.
        """
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "score": 42.5,
            "arxiv_id": "2301.12345",
            "altmetric_id": 9876543,
            "title": "Test Paper Title",
        }

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        # Act
        result = self.client.fetch_by_arxiv_id("2301.12345")

        # Assert
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["score"], 42.5)
        self.assertEqual(result["arxiv_id"], "2301.12345")

        # Verify the correct URL was called
        mock_session_instance.get.assert_called_once_with(
            "https://api.altmetric.com/v1/arxiv/2301.12345",
            headers=self.client.headers,
            timeout=self.client.timeout,
        )

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_arxiv_id_not_found(self, mock_session):
        """
        Test arXiv ID fetch when paper is not found in Altmetric.
        """
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 404

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        # Act
        result = self.client.fetch_by_arxiv_id("9999.99999")

        # Assert
        self.assertIsNone(result)

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_arxiv_id_rate_limited(self, mock_session):
        """
        Test arXiv ID fetch when rate limited.
        """
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = Exception("Rate limited")

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        # Act
        result = self.client.fetch_by_arxiv_id("2301.12345")

        # Assert
        self.assertIsNone(result)
        mock_response.raise_for_status.assert_called_once()

    def test_fetch_empty_arxiv_id(self):
        """
        Test fetch with empty arXiv ID.
        """
        result = self.client.fetch_by_arxiv_id("")
        self.assertIsNone(result)

        result = self.client.fetch_by_arxiv_id(None)
        self.assertIsNone(result)

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_arxiv_id_network_error(self, mock_session):
        """
        Test arXiv ID fetch with network error.
        """
        # Arrange
        mock_session_instance = Mock()
        mock_session_instance.get.side_effect = Exception("Network error")
        mock_session.return_value.__enter__.return_value = mock_session_instance

        # Act
        result = self.client.fetch_by_arxiv_id("2301.12345")

        # Assert
        self.assertIsNone(result)

    @patch("paper.ingestion.clients.altmetric.retryable_requests_session")
    def test_fetch_by_arxiv_id_with_version(self, mock_session):
        """
        Test arXiv ID fetch with version number (e.g., 2301.12345v1).
        """
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "score": 25.0,
            "arxiv_id": "2301.12345v1",
            "altmetric_id": 1111111,
        }

        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        # Act
        result = self.client.fetch_by_arxiv_id("2301.12345v1")

        # Assert
        self.assertIsNotNone(result)
        self.assertEqual(result["arxiv_id"], "2301.12345v1")

        # Verify the URL includes the version
        mock_session_instance.get.assert_called_once_with(
            "https://api.altmetric.com/v1/arxiv/2301.12345v1",
            headers=self.client.headers,
            timeout=self.client.timeout,
        )
