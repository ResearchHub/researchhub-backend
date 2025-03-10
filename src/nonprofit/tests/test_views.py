from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class NonprofitOrgViewSetTests(APITestCase):
    """
    Test cases for the NonprofitOrgViewSet class.

    These tests verify that our API correctly proxies requests to the Endaoment API
    for nonprofit organization searches. The tests focus on:

    1. Correctly passing user-provided parameters to the Endaoment API
    2. Applying proper default values when parameters are not provided
    3. Verifying response structure rather than exact values to ensure test resilience

    We use mocking to avoid making actual external API calls during testing.
    """

    def setUp(self):
        """
        Set up test data and common variables used across test methods.

        This includes API URLs and a sample response structure from Endaoment.
        The exact values in mock_endaoment_response aren't important - we're
        testing that our API correctly passes parameters and returns the structure.
        """
        self.search_url = reverse("nonprofit_orgs-search")
        self.endaoment_api_url = "https://api.endaoment.org/v1/sdk/orgs/search"
        # Sample response - exact values don't matter for our tests
        self.mock_endaoment_response = [
            {
                "id": "75f9643f-3927-49a2-8f3f-19f232d654c8",
                "name": "Endaoment",
                "ein": "844661797",
                "deployments": [
                    {
                        "isDeployed": True,
                        "chainId": 8453,
                        "address": "0x7ecc1d4936a973ec3b153c0c713e0f71c59abf53",
                    }
                ],
                "logoUrl": "https://example.com/logo.png",
                "nteeCode": "T12",
                "nteeDescription": "Fund Raising and/or Fund Distribution",
                "description": "Endaoment is a public Community Foundation",
                "address": {"region": "CA", "country": "USA"},
                "endaomentUrl": "https://app.endaoment.org/orgs/844661797",
                "contibutionCount": 146,
                "contibutionTotal": "$4,053,826.01",
            }
        ]

    def _verify_response_structure(self, response_data):
        """
        Helper method to verify response structure without depending on exact values.

        This makes our tests resilient to data changes in the Endaoment API.
        We check that the data is a list of properly structured objects.
        """
        # Check response is a list
        self.assertIsInstance(response_data, list)
        if not response_data:
            return  # Empty list is valid

        # Check first item structure
        org = response_data[0]
        self.assertIsInstance(org, dict)

        # Verify required fields exist
        self.assertIn("id", org)
        self.assertIn("name", org)

        # Check nested structures if they exist
        if "deployments" in org:
            self.assertIsInstance(org["deployments"], list)

        if "address" in org:
            self.assertIsInstance(org["address"], dict)

    @patch("utils.endaoment.requests.get")
    def test_search_with_parameters(self, mock_get):
        """
        Test searching for nonprofit organizations with full set of parameters.

        Verifies that all parameters are correctly passed to the Endaoment API,
        including proper URL encoding of special characters.
        """
        # Configure the mock to return a success response with our test data
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_endaoment_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Make request to the API with search parameters
        params = {
            "searchTerm": "Endaoment",
            "nteeMajorCodes": "A,B,T",
            "nteeMinorCodes": "A10,B21,T12",
            "countries": "USA,BRA,GBR",
            "count": "15",
            "offset": "0",
        }
        response = self.client.get(self.search_url, params)

        # Verify response status and structure (not exact values)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._verify_response_structure(response.data)

        # Verify the response data comes from our mock
        self.assertEqual(response.data, self.mock_endaoment_response)

        # Verify the mock was called with correct parameters
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertIn(self.endaoment_api_url, args[0])
        self.assertEqual(kwargs["headers"], {"accept": "application/json"})
        self.assertEqual(kwargs["timeout"], 10)

        # Verify query parameters, including proper URL encoding
        query_url = args[0]
        self.assertIn("searchTerm=Endaoment", query_url)
        self.assertIn("nteeMajorCodes=A%2CB%2CT", query_url)  # URL encoded
        self.assertIn("nteeMinorCodes=A10%2CB21%2CT12", query_url)  # URL encoded
        self.assertIn("countries=USA%2CBRA%2CGBR", query_url)  # URL encoded
        self.assertIn("count=15", query_url)
        self.assertIn("offset=0", query_url)

    @patch("utils.endaoment.requests.get")
    def test_search_with_minimal_parameters(self, mock_get):
        """
        Test searching for nonprofit organizations with only a search term.

        This tests that our API works with minimal parameters and still
        handles the response correctly.
        """
        # Configure the mock to return a success response with our test data
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_endaoment_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Make request to the API with minimal parameters
        params = {
            "searchTerm": "Endaoment",
        }
        response = self.client.get(self.search_url, params)

        # Verify response status and structure
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._verify_response_structure(response.data)

        # Verify query parameters
        args, _ = mock_get.call_args
        query_url = args[0]
        self.assertIn("searchTerm=Endaoment", query_url)

    @patch("utils.endaoment.requests.get")
    def test_search_with_default_parameters(self, mock_get):
        """
        Test that default parameters are correctly applied.

        This ensures our API adds default values for count and offset
        when not explicitly provided by the user.
        """
        # Configure the mock to return a success response
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_endaoment_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        # Make request with just a search term
        params = {"searchTerm": "Endaoment"}
        response = self.client.get(self.search_url, params)

        # Verify response status and structure
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._verify_response_structure(response.data)

        # Verify the default parameters were applied
        args, _ = mock_get.call_args
        query_url = args[0]
        self.assertIn("count=15", query_url)
        self.assertIn("offset=0", query_url)
