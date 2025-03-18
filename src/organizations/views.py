from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from organizations.serializers import (
    NonprofitFundraiseLinkSerializer,
    NonprofitOrgSerializer,
)
from organizations.services.endaoment_service import EndaomentService
from purchase.models import Fundraise


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


class NonprofitFundraiseLinkViewSet(viewsets.ViewSet):
    """
    ViewSet for managing nonprofit-fundraise links.

    This viewset provides endpoints to:
    1. Create or retrieve a nonprofit organization
    2. Link a nonprofit to a fundraise
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"])
    def create_nonprofit(self, request):
        """
        Create or retrieve a nonprofit organization.

        Request Body:
            - name: Name of the nonprofit organization
            - ein: Employer Identification Number (optional)
            - endaoment_org_id: Unique ID in Endaoment system
            - base_wallet_address: Blockchain wallet address (optional)

        Returns:
            - id: ID of the nonprofit organization
            - name: Name of the nonprofit organization
            - ein: Employer Identification Number
            - endaoment_org_id: Unique ID in Endaoment system
            - base_wallet_address: Blockchain wallet address
        """
        endaoment_org_id = request.data.get("endaoment_org_id")
        if not endaoment_org_id:
            return Response(
                {"error": "endaoment_org_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = request.data.get("name")
        if not name:
            return Response(
                {"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Try to find existing nonprofit by endaoment_org_id
        nonprofit = NonprofitOrg.objects.filter(
            endaoment_org_id=endaoment_org_id
        ).first()

        if nonprofit:
            # Check if any fields have changed
            has_changes = False
            if nonprofit.name != name:
                has_changes = True
                nonprofit.name = name

            ein = request.data.get("ein", "")
            if nonprofit.ein != ein and ein:
                has_changes = True
                nonprofit.ein = ein

            base_wallet_address = request.data.get("base_wallet_address", "")
            if (
                nonprofit.base_wallet_address != base_wallet_address
                and base_wallet_address
            ):
                has_changes = True
                nonprofit.base_wallet_address = base_wallet_address

            # If any fields changed, save the updated nonprofit
            if has_changes:
                nonprofit.save()

            # Return the nonprofit (updated or not)
            serializer = NonprofitOrgSerializer(nonprofit)
            return Response(serializer.data)

        # Create new nonprofit
        serializer = NonprofitOrgSerializer(
            data={
                "name": name,
                "ein": request.data.get("ein", ""),
                "endaoment_org_id": endaoment_org_id,
                "base_wallet_address": request.data.get("base_wallet_address", ""),
            }
        )

        if serializer.is_valid():
            nonprofit = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def link_to_fundraise(self, request):
        """
        Link a nonprofit organization to a fundraise.

        Request Body:
            - nonprofit_id: ID of the nonprofit organization
            - fundraise_id: ID of the fundraise
            - note: Notes about this specific link (optional)

        Returns:
            - id: ID of the nonprofit-fundraise link
            - nonprofit: Nonprofit organization details
            - fundraise: Fundraise details
            - note: Notes about this specific link
        """
        nonprofit_id = request.data.get("nonprofit_id")
        if not nonprofit_id:
            return Response(
                {"error": "nonprofit_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fundraise_id = request.data.get("fundraise_id")
        if not fundraise_id:
            return Response(
                {"error": "fundraise_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate nonprofit exists
        try:
            nonprofit = NonprofitOrg.objects.get(id=nonprofit_id)
        except NonprofitOrg.DoesNotExist:
            return Response(
                {"error": "Nonprofit organization not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Validate fundraise exists
        try:
            fundraise = Fundraise.objects.get(id=fundraise_id)
        except Fundraise.DoesNotExist:
            return Response(
                {"error": "Fundraise not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Check if link already exists
        existing_link = NonprofitFundraiseLink.objects.filter(
            nonprofit=nonprofit,
            fundraise=fundraise,
        ).first()

        if existing_link:
            # Update note if provided
            if "note" in request.data:
                existing_link.note = request.data.get("note", "")
                existing_link.save()

            serializer = NonprofitFundraiseLinkSerializer(existing_link)
            return Response(serializer.data)

        # Create new link
        serializer = NonprofitFundraiseLinkSerializer(
            data={
                "nonprofit": nonprofit.id,
                "fundraise": fundraise.id,
                "note": request.data.get("note", ""),
            }
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
