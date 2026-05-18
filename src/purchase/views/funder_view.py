from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from purchase.models import Grant
from purchase.serializers.funding_impact_serializer import FundingImpactSerializer
from purchase.serializers.funding_overview_serializer import FundingOverviewSerializer
from purchase.serializers.grant_overview_serializer import GrantOverviewSerializer
from purchase.services.funding_impact_service import FundingImpactService
from purchase.services.funding_overview_service import (
    FundingOverviewService,
    GrantOverviewService,
)


class FunderViewSet(viewsets.ViewSet):
    """Funder dashboard endpoints for overview and impact metrics."""

    def dispatch(self, request, *args, **kwargs):
        self.funding_overview_service = kwargs.pop(
            "funding_overview_service", FundingOverviewService()
        )
        self.funding_impact_service = kwargs.pop(
            "funding_impact_service", FundingImpactService()
        )
        self.grant_overview_service = kwargs.pop(
            "grant_overview_service", GrantOverviewService()
        )
        return super().dispatch(request, *args, **kwargs)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def funding_overview(self, request, *args, **kwargs):
        """Return funding overview metrics for the authenticated user."""
        data = self.funding_overview_service.get_funding_overview(request.user)
        serializer = FundingOverviewSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def funding_impact(self, request, *args, **kwargs):
        """Return funding impact metrics for the authenticated user."""
        data = self.funding_impact_service.get_funding_impact_overview(request.user)
        serializer = FundingImpactSerializer(data)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def grant_overview(self, request, pk=None, *args, **kwargs):
        """Return dashboard metrics for a grant owned by the authenticated user."""
        grant = Grant.objects.filter(unified_document__posts__id=pk).first()
        if not grant:
            return Response(status=404)
        if request.user != grant.created_by and not request.user.moderator:
            return Response({"message": "Permission denied"}, status=403)
        data = self.grant_overview_service.get_grant_overview(request.user, grant)
        serializer = GrantOverviewSerializer(data)
        return Response(serializer.data)
