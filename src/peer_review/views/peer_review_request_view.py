from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated,
)
from peer_review.models import PeerReviewRequest
from peer_review.serializers import (
    PeerReviewRequestSerializer,
)
from peer_review.permissions import (
    IsAllowedToRequest,
    IsAllowedToList,
    IsAllowedToRetrieve
)
from rest_framework.response import Response
from rest_framework.decorators import action
from utils.http import POST


class PeerReviewRequestViewSet(ModelViewSet):
    permission_classes = (
        IsAuthenticated,
        (IsAllowedToList|IsAllowedToRetrieve),
    )
    serializer_class = PeerReviewRequestSerializer
    queryset = PeerReviewRequest.objects.all()

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.serializer_class(instance)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=[POST],
        permission_classes=[IsAllowedToRequest]
    )
    def request_review(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data)

    def list(self, request, pk=None):
        queryset = self.get_queryset()

        if request.user.moderator:
            queryset = self.queryset
        else:
            queryset = self.queryset.filter(requested_by_user=request.user)

        page = self.paginate_queryset(queryset)
        serializer = PeerReviewRequestSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
