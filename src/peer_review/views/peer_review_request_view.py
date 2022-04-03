from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated
)
from peer_review.models import PeerReviewRequest
from peer_review.serializers import PeerReviewRequestSerializer
from rest_framework.response import Response
from rest_framework.decorators import action


class PeerReviewRequestViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = PeerReviewRequestSerializer

    @action(
        detail=True,
        methods=['post'],
        # permission_classes=[HasDocumentCensorPermission]
    )
    def request_review(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        print('to implement')

    def invite_reviewers(self):
        print('to implement')

    def accept_review_request(self):
        print('to implement')

    def decline_review_request(self):
        print('to implement')

    def accept_review(self):
        print('to implement')