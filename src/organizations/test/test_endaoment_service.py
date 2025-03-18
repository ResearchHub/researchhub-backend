from unittest.mock import MagicMock, patch

from django.test import TestCase
from requests.exceptions import HTTPError, RequestException

from organizations.services.endaoment_service import EndaomentService


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

    def test_init_with_custom_url(self):
        """Test initialization with a custom base URL."""
        custom_url = "https://custom-api.example.com"
        service = EndaomentService(base_url=custom_url)
        self.assertEqual(service.base_url, custom_url)

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

    @patch("requests.get")
    def test_search_nonprofit_orgs_http_error(self, mock_get):
        """Test handling of HTTP errors with status code."""
        # Create a mock response with a status code
        mock_error = HTTPError("Not Found")
        mock_error.response = MagicMock()
        mock_error.response.status_code = 404
        mock_get.side_effect = mock_error

        # Call service method and verify error response
        result = self.service.search_nonprofit_orgs(search_term="Test")
        self.assertEqual(
            result,
            {
                "error": "Not Found",
                "status": 404,
            },
        )

    @patch("requests.get")
    def test_search_nonprofit_orgs_request_exception(self, mock_get):
        """Test handling of request exceptions."""
        # Create a RequestException without a response
        mock_error = RequestException("Connection Error")
        mock_get.side_effect = mock_error

        # Call service method and verify error response
        result = self.service.search_nonprofit_orgs(search_term="Test")
        self.assertEqual(
            result,
            {
                "error": "Connection Error",
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

    @patch("requests.get")
    def test_search_nonprofit_orgs_all_params(self, mock_get):
        """Test all parameters are correctly passed."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Call service method with all parameters
        result = self.service.search_nonprofit_orgs(
            search_term="Test",
            ntee_major_codes="A,B,C",
            ntee_minor_codes="A10,B20",
            countries="USA,CAN",
            count=20,
            offset=10,
        )

        # Verify response
        self.assertEqual(result, self.mock_response)

        # Verify all parameters were included
        args, _ = mock_get.call_args
        query_url = args[0]
        self.assertIn("searchTerm=Test", query_url)
        self.assertIn("nteeMajorCodes=A%2CB%2CC", query_url)
        self.assertIn("nteeMinorCodes=A10%2CB20", query_url)
        self.assertIn("countries=USA%2CCAN", query_url)
        self.assertIn("count=20", query_url)
        self.assertIn("offset=10", query_url)
