from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated,
)
from peer_review.models import PeerReviewRequest
from peer_review.serializers import (
    PeerReviewRequestSerializer,
    DynamicPeerReviewRequestSerializer,
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
        context = self._get_serializer_context()
        serializer = DynamicPeerReviewRequestSerializer(
            page,
            _include_fields=[
                'id',
                'unified_document',
                'requested_by_user'
            ],
            context=context,
            many=True
        )
        return self.get_paginated_response(serializer.data)

    def _get_serializer_context(self):
        context = {
            'pr_dprrs_get_requested_by_user': {
                '_include_fields': [
                    'id',
                    'first_name',
                    'last_name',
                    'author_profile',
                ]
            },
            'usr_dus_get_author_profile': {
                '_include_fields': [
                    'id',
                ]
            }
        }

        return context