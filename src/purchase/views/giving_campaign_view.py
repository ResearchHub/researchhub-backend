from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from purchase.models import GivingCampaign
from purchase.serializers.giving_campaign_serializer import GivingCampaignSerializer
from purchase.services.giving_campaign_service import GivingCampaignService


class GivingCampaignViewSet(viewsets.GenericViewSet):
    """Public live summary of a giving campaign, looked up by slug."""

    queryset = GivingCampaign.objects.select_related("featured_grant").prefetch_related(
        "challenges__hub"
    )
    lookup_field = "slug"
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        self.giving_campaign_service = kwargs.pop(
            "giving_campaign_service", GivingCampaignService()
        )
        return super().dispatch(request, *args, **kwargs)

    @method_decorator(cache_page(60))
    def retrieve(self, request, *args, **kwargs):
        """Return the campaign's totals and challenge progress."""
        data = self.giving_campaign_service.summarize_campaign(self.get_object())
        return Response(GivingCampaignSerializer(data).data)
