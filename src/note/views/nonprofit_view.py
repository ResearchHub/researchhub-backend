from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from note.services.endaoment_service import EndaomentService


class NonprofitOrgViewSet(viewsets.ViewSet):
    """
    ViewSet for nonprofit organizations.

    This viewset provides an API to search for nonprofit organizations
    by proxying requests to the Endaoment API.
    """

    permission_classes = [AllowAny]
    endaoment_service_class = EndaomentService

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._endaoment_service = None

    @property
    def endaoment_service(self):
        """Lazy initialization of the service for better testability."""
        if self._endaoment_service is None:
            self._endaoment_service = self.endaoment_service_class()
        return self._endaoment_service

    @endaoment_service.setter
    def endaoment_service(self, service):
        """Setter for dependency injection in tests."""
        self._endaoment_service = service

    @action(detail=False, methods=["get"])
    def search(self, request):
        """
        Search for nonprofit organizations.

        Query Parameters:
            - searchTerm: Term to search for nonprofit organizations
            - nteeMajorCodes: Comma-separated list of NTEE major codes
            - nteeMinorCodes: Comma-separated list of NTEE minor codes
            - countries: Comma-separated list of countries
            - count: Number of results to return (default: 15)
            - offset: Offset for pagination (default: 0)
        """
        search_term = request.query_params.get("searchTerm")
        ntee_major_codes = request.query_params.get("nteeMajorCodes")
        ntee_minor_codes = request.query_params.get("nteeMinorCodes")
        countries = request.query_params.get("countries")

        try:
            count = int(request.query_params.get("count", 15))
        except (TypeError, ValueError):
            count = 15

        try:
            offset = int(request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0

        result = self.endaoment_service.search_nonprofit_orgs(
            search_term=search_term,
            ntee_major_codes=ntee_major_codes,
            ntee_minor_codes=ntee_minor_codes,
            countries=countries,
            count=count,
            offset=offset,
        )

        return Response(result)
