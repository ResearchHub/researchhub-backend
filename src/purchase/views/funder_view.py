from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from purchase.serializers.funding_impact_serializer import FundingImpactSerializer
from purchase.serializers.funding_overview_serializer import FundingOverviewSerializer
from purchase.services.funding_impact_service import FundingImpactService
from purchase.services.funding_overview_service import FundingOverviewService
from user.models import User


# Temporary function for testing different user data, will be removed before release
def _resolve_target_user(request) -> User | None:
    """Return the user specified by ?user_id, falling back to the requester."""
    user_id = request.query_params.get("user_id")
    if user_id:
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
    return request.user


class FunderViewSet(viewsets.ViewSet):
    """Funder dashboard endpoints for overview and impact metrics."""

    def dispatch(self, request, *args, **kwargs):
        self.funding_overview_service = kwargs.pop(
            "funding_overview_service", FundingOverviewService()
        )
        self.funding_impact_service = kwargs.pop(
            "funding_impact_service", FundingImpactService()
        )
        return super().dispatch(request, *args, **kwargs)

    @action(detail=False, methods=["get"], permission_classes=[AllowAny])
    def funding_overview(self, request, *args, **kwargs):
        """Return funding overview metrics. Accepts optional ?user_id param."""
        user = _resolve_target_user(request)
        if user is None:
            return Response({"error": "User not found"}, status=404)
        data = self.funding_overview_service.get_funding_overview(user)
        serializer = FundingOverviewSerializer(data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def funding_impact(self, request, *args, **kwargs):
        """Return funding impact metrics. Accepts optional ?user_id param."""
        user = _resolve_target_user(request)
        if user is None:
            return Response({"error": "User not found"}, status=404)
        data = self.funding_impact_service.get_funding_impact_overview(user)
        serializer = FundingImpactSerializer(data)
        return Response(serializer.data)
