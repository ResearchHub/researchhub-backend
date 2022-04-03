from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import (
    IsAuthenticated
)


class PeerReviewViewSet(ModelViewSet):
    permission_classes = [
        IsAuthenticated,
    ]

    def create_review_decision(self):
        print('to implement')

    def list(self, request, *args, **kwargs):
        print('to implement')

    def retrieve(self, request, *args, **kwargs):
        print('to implement')
