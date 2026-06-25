from django.db.models import Prefetch, QuerySet
from rest_framework import mixins, viewsets

from purchase.models import Grant
from researchhub_document.models import ResearchhubPost, ResearchJourney
from researchhub_document.serializers.research_journey_tracker_serializer import (
    ResearchJourneyTrackerSerializer,
)


class ResearchJourneyTrackerViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only endpoint for research journey tracker metadata."""

    serializer_class = ResearchJourneyTrackerSerializer
    permission_classes = []

    def get_queryset(self) -> QuerySet[ResearchJourney]:
        """Return journeys connected to at least one visible stage post."""
        visible_post_ids = ResearchhubPost.objects.visible_to(
            self.request.user
        ).values_list("id", flat=True)
        grants = Grant.objects.select_related("unified_document")

        return (
            ResearchJourney.objects.filter(stage_posts__id__in=visible_post_ids)
            .select_related(
                "grant_post",
                "grant_post__unified_document",
                "preregistration_post",
                "preregistration_post__unified_document",
            )
            .prefetch_related(
                "stage_posts",
                "stage_posts__unified_document",
                Prefetch("grant_post__unified_document__grants", queryset=grants),
            )
            .distinct()
        )
