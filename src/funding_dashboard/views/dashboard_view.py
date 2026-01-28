from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from funding_dashboard.serializers import DashboardOverviewSerializer
from funding_dashboard.services import DashboardService


class FundingDashboardViewSet(ViewSet):
    """API endpoint for funder dashboard metrics."""

    permission_classes = [IsAuthenticated]
    http_method_names = ["get"]

    @action(detail=False, methods=["get"])
    def overview(self, request: Request) -> Response:
        """Return dashboard overview metrics for the authenticated user."""
        service = DashboardService(request.user)
        serializer = DashboardOverviewSerializer(service.get_overview())
        return Response(serializer.data)
