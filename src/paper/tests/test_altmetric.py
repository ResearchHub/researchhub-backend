from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.services.altmetric import Altmetric


class TestAltmetric(TestCase):
    def setUp(self):
        self.altmetric = Altmetric()

    @patch("paper.services.altmetric.retryable_requests_session")
    def test_get_altmetric_data_success(self, mock_session):
        """Test successful Altmetric data retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "score": 100,
            "cited_by_posts_count": 50,
            "doi": "10.1038/nature12373",
        }

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.altmetric.get_altmetric_data("10.1038/nature12373")

        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["cited_by_posts_count"], 50)

        # Check the correct URL was called
        mock_session_instance.get.assert_called_once_with(
            "https://api.altmetric.com/v1/doi/10.1038/nature12373",
            headers=self.altmetric.base_headers,
            timeout=10,
        )

    @patch("paper.services.altmetric.retryable_requests_session")
    def test_get_altmetric_data_not_found(self, mock_session):
        """Test when DOI is not found in Altmetric."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.altmetric.get_altmetric_data("10.1038/notfound")

        self.assertIsNone(result)

    @patch("paper.services.altmetric.retryable_requests_session")
    def test_get_altmetric_data_rate_limited(self, mock_session):
        """Test rate limiting triggers retry."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = Exception("Rate limited")

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.altmetric.get_altmetric_data("10.1038/nature12373")

        self.assertIsNone(result)
        mock_response.raise_for_status.assert_called_once()

    @patch("paper.services.altmetric.retryable_requests_session")
    def test_get_altmetric_data_server_error(self, mock_session):
        """Test handling of unexpected server errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_session_instance = MagicMock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.altmetric.get_altmetric_data("10.1038/nature12373")

        self.assertIsNone(result)

    def test_get_altmetric_data_empty_doi(self):
        """Test with empty DOI."""
        result = self.altmetric.get_altmetric_data("")
        self.assertIsNone(result)

        result = self.altmetric.get_altmetric_data(None)
        self.assertIsNone(result)

    def test_clean_doi_with_url_prefix(self):
        """Test DOI cleaning when URL prefix is present."""
        with patch(
            "paper.services.altmetric.retryable_requests_session"
        ) as mock_session:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"score": 100}

            mock_session_instance = MagicMock()
            mock_session_instance.get.return_value = mock_response
            mock_session.return_value.__enter__.return_value = mock_session_instance

            # Test with full URL
            self.altmetric.get_altmetric_data("https://doi.org/10.1038/nature12373")

            # Check that the DOI was cleaned
            mock_session_instance.get.assert_called_with(
                "https://api.altmetric.com/v1/doi/10.1038/nature12373",
                headers=self.altmetric.base_headers,
                timeout=10,
            )

    @patch("paper.services.altmetric.retryable_requests_session")
    def test_get_altmetric_data_network_error(self, mock_session):
        """Test handling of network errors."""
        mock_session_instance = MagicMock()
        mock_session_instance.get.side_effect = Exception("Network error")
        mock_session.return_value.__enter__.return_value = mock_session_instance

        result = self.altmetric.get_altmetric_data("10.1038/nature12373")

        self.assertIsNone(result)
