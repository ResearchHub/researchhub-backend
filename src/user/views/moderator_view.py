from rest_framework.decorators import action
from rest_framework.viewsets import ModelViewSet

from user.filters import RiskScoreEventFilter
from user.models import User
from user.pagination import RiskScoreEventPagination
from user.permissions import IsModerator, UserIsEditor
from user.related_models.risk_score_model import RiskScoreEvent
from user.serializers import ModeratorUserSerializer, RiskScoreEventSerializer
from user.services.risk_score_insights_service import (
    build_event_details,
    build_insights,
)


class ModeratorView(ModelViewSet):
    queryset = User.objects.select_related(
        "userverification",
        "risk_score",
    )
    serializer_class = ModeratorUserSerializer
    permission_classes = [UserIsEditor | IsModerator]

    @action(detail=True, methods=["get"])
    def user_details(self, request, pk=None, **kwargs):
        return super().retrieve(request, pk, **kwargs)

    @action(detail=True, methods=["get"], permission_classes=[IsModerator])
    def risk_score_events(self, request, pk=None, **kwargs):
        user = self.get_object()
        events = RiskScoreEvent.objects.filter(user=user).select_related(
            "source_content_type"
        )
        events = RiskScoreEventFilter(request.query_params, queryset=events).qs

        paginator = RiskScoreEventPagination()
        page = paginator.paginate_queryset(events, request)

        details = build_event_details(page)
        serializer = RiskScoreEventSerializer(
            page, many=True, context={"details": details}
        )

        return paginator.get_paginated_response(
            serializer.data, insights=build_insights(user)
        )
