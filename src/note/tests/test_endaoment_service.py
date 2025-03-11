from unittest.mock import MagicMock, patch

from django.test import TestCase

from note.services.endaoment_service import EndaomentService


class EndaomentServiceTests(TestCase):
    """Test cases for the EndaomentService class."""

    def setUp(self):
        """Set up test data and common variables."""
        self.service = EndaomentService()
        self.mock_response = [
            {
                "id": "75f9643f-3927-49a2-8f3f-19f232d654c8",
                "name": "Endaoment",
                "ein": "844661797",
            }
        ]

    @patch("requests.get")
    def test_search_nonprofit_orgs_success(self, mock_get):
        """Test successful search for nonprofit organizations."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Call service method
        result = self.service.search_nonprofit_orgs(
            search_term="Endaoment",
            ntee_major_codes="A,B",
            count=15,
            offset=0,
        )

        # Verify response
        self.assertEqual(result, self.mock_response)

        # Verify request
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertIn(self.service.base_url, args[0])
        self.assertEqual(kwargs["headers"], {"accept": "application/json"})
        self.assertEqual(kwargs["timeout"], 10)

        # Verify query parameters
        query_url = args[0]
        self.assertIn("searchTerm=Endaoment", query_url)
        self.assertIn("nteeMajorCodes=A%2CB", query_url)
        self.assertIn("count=15", query_url)
        self.assertIn("offset=0", query_url)

    @patch("requests.get")
    def test_search_nonprofit_orgs_error(self, mock_get):
        """Test error handling in search."""
        # Configure mock to raise an error
        mock_error = Exception("API Error")
        mock_get.side_effect = mock_error

        # Call service method and verify error response
        result = self.service.search_nonprofit_orgs(search_term="Test")
        self.assertEqual(
            result,
            {
                "error": str(mock_error),
                "status": 500,
            },
        )

    def test_search_nonprofit_orgs_default_params(self):
        """Test default parameters are correctly set."""
        with patch("requests.get") as mock_get:
            # Configure mock
            mock_response = MagicMock()
            mock_response.json.return_value = self.mock_response
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            # Call service method with minimal parameters
            self.service.search_nonprofit_orgs()

            # Verify default parameters
            args, _ = mock_get.call_args
            query_url = args[0]
            self.assertIn("count=15", query_url)
            self.assertIn("offset=0", query_url)
