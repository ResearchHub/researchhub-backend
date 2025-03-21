from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from organizations.services.endaoment_service import EndaomentService
from organizations.views import NonprofitOrgViewSet


class NonprofitOrgViewSetTests(APITestCase):
    """Test cases for the NonprofitOrgViewSet class."""

    def setUp(self):
        """Set up test data and common variables."""
        self.search_url = reverse("nonprofit-orgs-search")
        self.mock_response = [
            {
                "id": "75f9643f-3927-49a2-8f3f-19f232d654c8",
                "name": "Endaoment",
                "ein": "844661797",
            }
        ]

        # Create mock service
        self.mock_service = MagicMock(spec=EndaomentService)

        # Patch the service class to return our mock
        patcher = patch.object(
            NonprofitOrgViewSet,
            "endaoment_service_class",
            return_value=self.mock_service,
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_endaoment_service_property(self):
        """Test the endaoment_service property."""
        viewset = NonprofitOrgViewSet()

        # First access should initialize the service
        service = viewset.endaoment_service
        self.assertEqual(service, self.mock_service)

        # Second access should return the same instance
        service_again = viewset.endaoment_service
        self.assertEqual(service, service_again)

    def test_endaoment_service_setter(self):
        """Test the endaoment_service setter."""
        viewset = NonprofitOrgViewSet()
        custom_service = MagicMock()

        # Set a custom service
        viewset.endaoment_service = custom_service

        # Verify the service was set
        self.assertEqual(viewset.endaoment_service, custom_service)

    def test_search_with_parameters(self):
        """Test searching for nonprofit organizations with parameters."""
        # Configure mock service
        self.mock_service.search_nonprofit_orgs.return_value = self.mock_response

        # Make request with parameters
        params = {
            "searchTerm": "Endaoment",
            "nteeMajorCodes": "A,B,T",
            "nteeMinorCodes": "A10,B21,T12",
            "countries": "USA,BRA,GBR",
            "count": "15",
            "offset": "0",
        }
        response = self.client.get(self.search_url, params)

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, self.mock_response)

        # Verify service call
        self.mock_service.search_nonprofit_orgs.assert_called_once_with(
            search_term="Endaoment",
            ntee_major_codes="A,B,T",
            ntee_minor_codes="A10,B21,T12",
            countries="USA,BRA,GBR",
            count=15,
            offset=0,
        )

    def test_search_with_minimal_parameters(self):
        """Test searching with only required parameters."""
        # Configure mock service
        self.mock_service.search_nonprofit_orgs.return_value = self.mock_response

        # Make request with minimal parameters
        params = {"searchTerm": "Endaoment"}
        response = self.client.get(self.search_url, params)

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, self.mock_response)

        # Verify service call with default values
        self.mock_service.search_nonprofit_orgs.assert_called_once_with(
            search_term="Endaoment",
            ntee_major_codes=None,
            ntee_minor_codes=None,
            countries=None,
            count=15,
            offset=0,
        )

    def test_search_with_invalid_parameters(self):
        """Test searching with invalid parameters."""
        # Configure mock service
        self.mock_service.search_nonprofit_orgs.return_value = self.mock_response

        # Make request with invalid count/offset
        params = {
            "searchTerm": "Endaoment",
            "count": "invalid",
            "offset": "invalid",
        }
        response = self.client.get(self.search_url, params)

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, self.mock_response)

        # Verify service call with default values for invalid parameters
        self.mock_service.search_nonprofit_orgs.assert_called_once_with(
            search_term="Endaoment",
            ntee_major_codes=None,
            ntee_minor_codes=None,
            countries=None,
            count=15,
            offset=0,
        )

    def test_search_with_error_response(self):
        """Test handling of error responses from the service."""
        # Configure mock service to return an error
        error_response = {"error": "API Error", "status": 500}
        self.mock_service.search_nonprofit_orgs.return_value = error_response

        # Make request
        response = self.client.get(self.search_url, {"searchTerm": "Error"})

        # Verify response passes through the error
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, error_response)
